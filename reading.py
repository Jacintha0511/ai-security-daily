"""Public reading catalog and durable, version-aware editorial selections. No model API."""
from __future__ import annotations
import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import daily

THEMES = {
    '记忆投毒': ['memory poisoning', 'memory-poisoning', 'agent memory', 'persistent memory', 'contextual state', '记忆', '投毒'],
    '来源追踪': ['provenance', 'lineage', 'traceability', 'state-transfer', 'audit', '来源追踪'],
    '工具与权限': ['authorization', 'permission', 'capability', 'tool argument', 'tool metadata', 'tool-using', 'tool description', '权限'],
    '提示注入': ['prompt injection', 'prompt-injection', '提示注入'],
    '越狱与对齐': ['jailbreak', 'alignment', 'safeguard', '越狱', '对齐'],
    '其他 AI 安全': ['ai safety', 'llm safety', 'llm security', 'ai security', '大模型安全'],
}
FOCUS = {'记忆投毒', '来源追踪', '工具与权限'}
NOTE_FIELDS = {'headline', 'why_read', 'read_next', 'update_summary', 'substantive_update'}

def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

def version(item):
    return item.get('version') or item.get('updated_at') or item.get('published_at') or item['url']

def key(item):
    return item['id'] + ':' + version(item)

def clean_note(note):
    from enrich import plain
    if not isinstance(note, dict) or set(note) - NOTE_FIELDS:
        raise ValueError('invalid public recommendation')
    result = {}
    for name, value in note.items():
        if name == 'substantive_update':
            if type(value) is not bool: raise ValueError('update decision must be boolean')
            result[name] = value
        else:
            if not isinstance(value, str) or len(value) > (120 if name == 'headline' else 900):
                raise ValueError('recommendation text too long')
            result[name] = plain(value)
    if result.get('substantive_update') and not result.get('update_summary'):
        raise ValueError('substantive update needs an evidence-backed explanation')
    return result

def tags(item):
    content = ' '.join([item['title'], item.get('summary', ''), ' '.join(item.get('topics', []))]).lower()
    result = [name for name, words in THEMES.items() if any(w in content for w in words)]
    return result or ['其他 AI 安全']

def recent(item, now, days=7):
    value = item.get('updated_at') or item.get('published_at')
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return timedelta(0) <= now - date <= timedelta(days=days)
    except (AttributeError, ValueError, TypeError):
        return False

def eligible_repo(item, config):
    name = item['url'].split('github.com/')[-1].lower()
    registered = name in {s.lower() for s in config['seed_repos']}
    official = name in {s.lower() for s in config.get('verified_paper_repos', {})}
    return item.get('stars', 0) >= config.get('repo_policy', {}).get('min_stars', 100) or registered or official

def candidates(config, state, ids, data_dir, now):
    """Do not spend the next Codex batch on a version already featured."""
    old = read(data_dir / 'library.json', {'editions': {}})
    featured = {k for e in old.get('editions', {}).values() for values in e['items'].values() for k in values}
    used_ids = {k.split(':', 1)[0] for k in featured}
    known = {r['record_key']: r for r in old.get('items', [])}
    def needs_review(item):
        record = known.get(key(item), {})
        analysis = record.get('analysis')
        return key(item) not in featured and not (item['id'] in used_ids and analysis and not analysis.get('recommendation', {}).get('substantive_update'))
    values = [r for i in ids if (r := daily.rank(state['items'][i], config))]
    values.sort(key=lambda x: (bool(FOCUS.intersection(tags(x))), x['score'], x.get('published_at', '')), reverse=True)
    papers = [x for x in values if x['kind'] == 'paper' and needs_review(x) and recent(x, now)][:3]
    expanded = {**config, 'limits': {**config['limits'], 'repo': config['max_repos']}}
    repos = [x for x in daily.select_repositories(expanded, state, ids, now) if needs_review(x)][:1]
    news = [x for x in values if x['kind'] == 'news' and key(x) not in featured][:2]
    return {'paper': papers, 'repo': repos, 'news': news}

def sync(data_dir, now=None, config=None, persist=True):
    from enrich import validate_public
    validate_public(data_dir)
    now = now or datetime.now(timezone.utc)
    date = now.astimezone(daily.TZ).date().isoformat()
    config = config or read(daily.ROOT / 'config.json')
    for paper_url in config.get('verified_paper_repos', {}).values(): daily.safe_url(paper_url)
    previous = read(data_dir / 'library.json', {})
    # A same-day report can change and state retains only each item's latest version.
    # Preserve validated catalog versions so published editions keep their targets.
    if previous: validate_catalog(previous)
    records = {r['record_key']: dict(r) for r in previous.get('items', [])}
    reports = []
    for path in sorted((data_dir / 'reports').glob('*.json')):
        report = read(path); reports.append(report)
        for values in report['items'].values():
            for raw in values:
                item = daily.public_item(raw); k = key(item)
                prior = records.get(k, {})
                records[k] = {**item, 'record_key': k, 'first_recommended': prior.get('first_recommended', report['date']),
                              'last_recommended': report['date'], 'dates': list(dict.fromkeys(prior.get('dates', []) + [report['date']])), 'origin': 'history'}
    # Explicit public field projection; never deploy the state file or local packets.
    state = daily.load_state(data_dir / 'state.json')
    for raw in state['items'].values():
        if not daily.rank(raw, config): continue
        item = daily.public_item(raw); k = key(item)
        if k in records:
            records[k].update(item)
        else:
            records[k] = {**item, 'record_key': k, 'first_recommended': None, 'last_recommended': None, 'dates': [], 'origin': 'candidate'}
    idx = read(data_dir / 'analyses/index.json', {'items': {}})
    entries = sorted(idx['items'].values(), key=lambda v: v['updated_at'], reverse=True)
    for r in records.values():
        r['themes'] = tags(r); r['focus'] = bool(FOCUS.intersection(r['themes']))
        name = r['url'].split('github.com/')[-1].lower()
        r['project_role'] = '论文官方代码' if name in config.get('verified_paper_repos', {}) else '登记基准' if name in {s.lower() for s in config['seed_repos']} else '工程项目' if eligible_repo(r, config) and r['kind'] == 'repo' else '早期观察'
        entry = next((x for x in entries if x['item_id'] == r['id'] and x.get('requested_version') == version(r) and x.get('path') and x['status'] in {'ready', 'partial'}), None)
        if r['kind'] != 'repo': r['project_role'] = ''
        r['analysis'] = None
        if entry:
            a = read(data_dir / 'analyses' / Path(entry['path']).name)
            note = clean_note(a.get('recommendation', {}))
            r['analysis'] = {k: a[k] for k in ['fingerprint', 'version', 'generated_at', 'status', 'verdict', 'overview']}
            r['analysis'].update(path=entry['path'], recommendation=note,
                code_checked=any(re.search(r'/blob/[0-9a-f]{40}/(?!tests?/|scripts?/|examples?/).*\.(py|ts|js|rs|go|java|cpp|c)$', x['url']) for x in a['sources']))
    # Keep already-published selections immutable across restarts and repeated builds.
    editions = previous.get('editions', {})
    for e in editions.values():
        if set(e) - {'items', 'note'} or set(e.get('items', {})) != {'paper', 'repo', 'news'}: raise ValueError('invalid reading edition')
        for kind, limit in [('paper', 3), ('repo', 1), ('news', 2)]:
            if len(e['items'][kind]) > limit or len(set(e['items'][kind])) != len(e['items'][kind]): raise ValueError('invalid edition slots')
            for k in e['items'][kind]:
                if k not in records or records[k]['kind'] != kind: raise ValueError('unknown reading record')
    edition = editions.setdefault(date, {'items': {'paper': [], 'repo': [], 'news': []}, 'note': '首次整理现有导读，包含此前收录的资料；不代表今天新发表。' if not previous else ''})
    used = {k for e in editions.values() for values in e['items'].values() for k in values}
    used_ids = {records[k]['id'] for k in used}
    pool = sorted(records.values(), key=lambda r: (r['focus'], r.get('updated_at') or r.get('published_at') or '', r.get('stars', 0)), reverse=True)
    for r in pool:
        k = r['record_key']; a = r['analysis']; kind = r['kind']
        if k in used or not a or not recent(r, now, 1 if kind == 'news' else 7 if kind == 'paper' else 180): continue
        note = a['recommendation']
        if not note.get('why_read') or not note.get('read_next'): continue
        # A different version is an update, not automatically a new recommendation.
        if r['id'] in used_ids and not note.get('substantive_update'): continue
        if r['id'] in {records[x]['id'] for values in edition['items'].values() for x in values}: continue
        if kind == 'repo' and (not eligible_repo(r, config) or not a['code_checked'] or not recent(r, now, 30)): continue
        limit = {'paper': 3, 'repo': 1, 'news': 2}[kind]
        if len(edition['items'][kind]) < limit:
            edition['items'][kind].append(k); used.add(k); used_ids.add(r['id'])
    result = {'schema_version': 1, 'initialized_on': previous.get('initialized_on', date), 'updated_at': daily.stamp(now),
              'themes': list(THEMES), 'items': sorted(records.values(), key=lambda r: r['record_key']), 'editions': editions}
    if previous and {k: v for k, v in result.items() if k != 'updated_at'} == {k: v for k, v in previous.items() if k != 'updated_at'}:
        result['updated_at'] = previous['updated_at']
    validate_catalog(result)
    if persist and result != previous: daily.atomic_json(data_dir / 'library.json', result)
    return result

def validate_catalog(value):
    from enrich import plain
    allowed = daily.ITEM_FIELDS | {'record_key', 'first_recommended', 'last_recommended', 'dates', 'origin', 'themes', 'focus', 'project_role', 'analysis'}
    if set(value) != {'schema_version', 'initialized_on', 'updated_at', 'themes', 'items', 'editions'}: raise ValueError('invalid catalog fields')
    def check(v):
        if isinstance(v, str): plain(v)
        elif isinstance(v, list):
            for x in v: check(x)
        elif isinstance(v, dict):
            for k, x in v.items(): plain(k); check(x)
    for r in value['items']:
        if set(r) - allowed or r['record_key'] != key(r): raise ValueError('non-public catalog item')
        if r['id'] != daily.public_item(r)['id']: raise ValueError('catalog identity mismatch')
        daily.safe_url(r['url'])
        a = r.get('analysis')
        if a:
            if set(a) != {'fingerprint', 'version', 'generated_at', 'status', 'verdict', 'overview', 'path', 'recommendation', 'code_checked'}: raise ValueError('invalid analysis preview')
            if a['path'] != f"data/analyses/{r['id']}-{a['fingerprint']}.json" or not re.fullmatch(r'[a-f0-9]{20}', a['fingerprint']): raise ValueError('invalid preview path')
            clean_note(a['recommendation'])
    check(value)
    return True

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('command', choices=['sync']); p.add_argument('--data-dir', type=Path, default=daily.ROOT / 'data')
    a = p.parse_args(); v = sync(a.data_dir); print(json.dumps({'status': 'reading_index_updated', 'records': len(v['items']), 'editions': len(v['editions'])}))
