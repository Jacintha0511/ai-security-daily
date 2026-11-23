"""Local reading packets and validated public analyses. Never calls a model API."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import httpx
from bs4 import BeautifulSoup

import daily

ROOT = daily.ROOT
LOCAL = ROOT / '.local'
ANALYSES = ROOT / 'data' / 'analyses'
TEMPLATES = {
    'paper': ['一分钟概览', '论文故事线', '威胁模型与边界', '方法与攻击实例', '实验设置', '关键结果', '贡献与局限', '复现与研究价值', '理解检测'],
    'repo': ['项目定位', '能力与边界', '架构与执行流程', '安全机制', '关键代码导读', '相关工作比较', '上手与资源', '成熟度与研究用途'],
    'news': ['发生了什么', '为什么相关', '第一手来源', '证据判断', '研究点评', '下一步阅读'],
}


def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]


def plain(value):
    if not isinstance(value, str) or len(value) > 15000:
        raise ValueError('invalid public text')
    if re.search(r'(?i)((?<![A-Za-z])[a-z]:[\\/]|\\\\|sk-[a-z0-9]{16}|gh[pousr]_[a-z0-9]+|wr_skey|access_token=|api_key=)', value):
        raise ValueError('private path or credential in public text')
    return value.strip()


def get_index():
    return read(ANALYSES / 'index.json', {'schema_version': 1, 'updated_at': None, 'items': {}})


def html_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    for e in soup(['script', 'style', 'nav', 'footer']):
        e.decompose()
    root = soup.find('article') or soup.find(id='js_content') or soup.body or soup
    lines = []
    for e in root.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'table', 'figcaption', 'pre']):
        if e.find_parent(['table', 'pre']):
            continue
        label = e.get('id') or (e.parent.get('id') if e.parent else '') or ''
        value = e.get_text(' ', strip=True)
        if e.name == 'table':
            value = '\n'.join(' | '.join(c.get_text(' ', strip=True) for c in row.find_all(['th', 'td'])) for row in e.find_all('tr'))
        if value:
            lines.append(f'[{label}] {value}')
    return '\n\n'.join(lines)


def prepare(date, refresh=False):
    report = read(ROOT / 'data' / 'reports' / (date + '.json'))
    if not report:
        return {'status': 'waiting_for_daily', 'date': date, 'jobs': []}
    jobs, index = [], get_index()
    changed = False
    with httpx.Client(timeout=35, follow_redirects=True, headers={'User-Agent': 'AI-Security-Daily-Reader/2.0'}) as web:
        for kind, count in [('paper', 3), ('repo', 1), ('news', 2)]:
            for item in report['items'][kind][:count]:
                folder = LOCAL / 'packets' / date / item['id']
                folder.mkdir(parents=True, exist_ok=True)
                old = read(folder / 'packet.json')
                version = item.get('version') or item.get('updated_at') or item.get('published_at') or item['url']
                if old and old['requested_version'] == version and old['sources'] and not old.get('errors') and not refresh:
                    packet = old
                else:
                    sources, errors = [], []
                    def save_source(url, content, label):
                        sid = 's' + str(len(sources) + 1)
                        name = sid + '.txt'
                        (folder / name).write_text(content, encoding='utf-8')
                        sources.append({'id': sid, 'url': daily.safe_url(url), 'label': label, 'file': name,
                                        'sha256': hashlib.sha256(content.encode()).hexdigest(), 'chars': len(content)})
                    try:
                        if kind == 'paper':
                            aid = item['url'].split('/')[-1] + item.get('version', '')
                            url = 'https://arxiv.org/html/' + aid
                            response = web.get(url)
                            content = html_text(response.text) if response.status_code == 200 else ''
                            if len(content) > 3500:
                                save_source(url, content, '论文 HTML 全文（含章节与图表标识）')
                            else:
                                from pypdf import PdfReader
                                url = 'https://arxiv.org/pdf/' + aid
                                response = web.get(url); response.raise_for_status()
                                (folder / 'paper.pdf').write_bytes(response.content)
                                pages = PdfReader(io.BytesIO(response.content)).pages
                                content = '\n\n'.join(f'[PDF 第 {i+1} 页]\n{p.extract_text() or ""}' for i, p in enumerate(pages))
                                if len(content) < 3500:
                                    raise ValueError('全文无法可靠提取')
                                save_source(url, content, '论文 PDF 全文（图像需另行查看，不凭提取文本推断图形）')
                            meta_response = web.get(item['url']); meta_response.raise_for_status()
                            meta = BeautifulSoup(meta_response.text, 'html.parser')
                            lines = []
                            for selector in ('.authors', '.comments', '.jref', '.dateline'):
                                node = meta.select_one(selector)
                                if node:
                                    lines.append(node.get_text(' ', strip=True))
                                    lines.extend(a.get('href','') for a in node.find_all('a') if a.get('href','').startswith('http'))
                            save_source(item['url'], '\n'.join(lines), 'arXiv 作者、发表状态与作者提供的链接')
                        elif kind == 'repo':
                            name = item['url'].split('github.com/')[-1]
                            meta = web.get('https://api.github.com/repos/' + name); meta.raise_for_status()
                            meta = meta.json()
                            if meta.get('private') is not False:
                                raise ValueError('repository not public')
                            response = web.get(f'https://api.github.com/repos/{name}/commits/' + meta['default_branch']); response.raise_for_status()
                            sha = response.json()['sha']; version = sha
                            tree = web.get(f'https://api.github.com/repos/{name}/git/trees/{sha}', params={'recursive': '1'}); tree.raise_for_status()
                            files = [v['path'] for v in tree.json()['tree'] if v['type'] == 'blob']
                            save_source(f'https://github.com/{name}/tree/{sha}', '\n'.join(files), '固定 commit 文件目录：' + sha)
                            candidates = sorted(files, key=lambda p: (0 if p.lower().startswith('readme') else 1 if p.lower().startswith('license') else 2 if p.endswith('.py') and not p.startswith('tests') else 3, len(p)))
                            candidates = [p for p in candidates if p.lower().startswith(('readme', 'license')) or p.endswith(('.py', '.toml', '.yaml'))][:9]
                            for path in candidates:
                                response = web.get(f'https://raw.githubusercontent.com/{name}/{sha}/{path}')
                                if response.status_code == 200 and len(response.content) < 200000:
                                    numbered = '\n'.join(f'{i+1}: {line}' for i, line in enumerate(response.text.splitlines()))
                                    save_source(f'https://github.com/{name}/blob/{sha}/{path}', numbered, path)
                        else:
                            cached = read(LOCAL / 'news-content.json', {})
                            content = cached.get(item['id'], '')
                            if not content:
                                response = web.get(item['url']); response.raise_for_status()
                                content = html_text(response.text)
                            if len(content) < 300 or any(t in content for t in ['环境异常', '完成验证']):
                                raise ValueError('正文不可读，不能进行全文点评')
                            save_source(item['url'], content, '报道正文')
                    except (httpx.HTTPError, ValueError, KeyError, ImportError) as exc:
                        errors.append(type(exc).__name__ + ': 材料获取失败；检查网络、全文或源站授权')
                    packet = {'schema_version': 1, 'item': item, 'requested_version': item.get('version') or item.get('updated_at') or item.get('published_at') or item['url'],
                              'source_version': version, 'fingerprint': digest([version, [s['sha256'] for s in sources]]),
                              'fetched_at': daily.stamp(), 'sources': sources, 'errors': errors, 'required_sections': TEMPLATES[kind]}
                    daily.atomic_json(folder / 'packet.json', packet)
                key = item['id'] + ':' + packet['fingerprint']
                entry = index['items'].get(key)
                done = entry and entry['status'] in {'ready', 'partial'} and not refresh
                jobs.append({'id': item['id'], 'kind': kind, 'packet': str(folder / 'packet.json'), 'cached': bool(done), 'sources': len(packet['sources'])})
                if not entry:
                    changed = True
                    index['items'][key] = {'item_id': item['id'], 'kind': kind, 'title': item['title'], 'version': packet['source_version'],
                        'fingerprint': packet['fingerprint'], 'requested_version': packet['requested_version'], 'report_date': date,
                        'status': 'pending' if packet['sources'] else 'failed', 'updated_at': daily.stamp(), 'path': None,
                        'message': '等待本机 Codex 全文解析' if packet['sources'] else '全文材料暂不可读，等待补跑'}
        if changed:
            index['updated_at'] = daily.stamp(); daily.atomic_json(ANALYSES / 'index.json', index)
    return {'status': 'prepared', 'date': date, 'jobs': jobs}


def accept(packet_path, draft_path):
    packet, draft = read(packet_path), read(draft_path)
    allowed = {'schema_version','item_id','fingerprint','status','model','verdict','overview','sections','limitations','checks','recommendation'}
    if set(draft) - allowed or draft.get('item_id') != packet['item']['id'] or draft.get('fingerprint') != packet['fingerprint']:
        raise ValueError('draft identity or public allowlist mismatch')
    if draft.get('status') not in {'ready', 'partial'} or not packet['sources']:
        raise ValueError('analysis needs readable source material')
    sources = {s['id']: s for s in packet['sources']}
    if len(draft.get('sections', [])) != len(packet['required_sections']):
        raise ValueError('missing analysis sections')
    clean_sections = []
    for expected, section in zip(packet['required_sections'], draft['sections']):
        if section.get('title') != expected or set(section) - {'title','paragraphs','bullets','table','diagram','qa','refs','stance'}:
            raise ValueError('invalid section')
        refs = section.get('refs', [])
        if not refs or any(set(r) - {'source','locator'} or r.get('source') not in sources or not plain(r.get('locator','')) for r in refs):
            raise ValueError('missing or invented source reference')
        # Validate every nested string and forbid additional executable markup fields.
        def clean(v):
            if isinstance(v, str): return plain(v)
            if isinstance(v, list): return [clean(x) for x in v]
            if isinstance(v, dict): return {plain(k): clean(x) for k,x in v.items()}
            if v is None or isinstance(v, (int,float,bool)): return v
            raise ValueError('invalid JSON value')
        clean_sections.append(clean(section))
    value = {'schema_version': 1, 'item_id': draft['item_id'], 'kind': packet['item']['kind'], 'title': packet['item']['title'],
             'url': packet['item']['url'], 'fingerprint': packet['fingerprint'], 'version': packet['source_version'],
             'status': draft['status'], 'model': plain(draft['model']), 'generated_at': daily.stamp(),
             'verdict': plain(draft['verdict']), 'overview': plain(draft['overview']), 'sections': clean_sections,
             'limitations': [plain(x) for x in draft.get('limitations',[])], 'checks': [plain(x) for x in draft.get('checks',[])],
             'sources': [{k:s[k] for k in ('id','url','label','sha256')} for s in sources.values()]}
    if 'recommendation' in draft:
        from reading import clean_note
        value['recommendation'] = clean_note(draft['recommendation'])
    name = value['item_id'] + '-' + value['fingerprint'] + '.json'
    daily.atomic_json(ANALYSES / name, value)
    index = get_index(); key = value['item_id'] + ':' + value['fingerprint']
    index['items'][key] = {'item_id': value['item_id'], 'kind': value['kind'], 'title': value['title'], 'version': value['version'],
        'requested_version': packet['requested_version'], 'fingerprint': value['fingerprint'], 'status': value['status'],
        'updated_at': value['generated_at'], 'path': 'data/analyses/' + name, 'message': value['verdict']}
    index['updated_at'] = daily.stamp(); daily.atomic_json(ANALYSES / 'index.json', index)
    return {'status': value['status'], 'path': 'data/analyses/' + name}


def import_news(data_dir, now=None):
    now = now or datetime.now(timezone.utc)
    date = now.astimezone(daily.TZ).date().isoformat()
    inbox = read(data_dir / 'news-inbox.json')
    report_path = data_dir / 'reports' / (date + '.json')
    report = read(report_path)
    if not inbox or not report:
        return {'status':'no_local_news'}
    recent = datetime.fromisoformat(inbox['collected_at']) >= now - timedelta(hours=26)
    config = read(ROOT / 'config.json')
    items = []
    if recent:
        for raw in inbox.get('items', []):
            item = daily.public_item(raw)
            published = item.get('published_at')
            if not published or not now-timedelta(hours=24) <= datetime.fromisoformat(published) <= now:
                continue
            result = daily.rank(item, config)
            if result: items.append(result)
    items = sorted({i['id']:i for i in items}.values(),key=lambda i:(-i['score'],i['id']))[:3]
    report['items']['news'] = items
    feeds = {f['name'] for f in config['feeds']}
    report['sources'] = [s for s in report['sources'] if s['name'] not in feeds]
    for status in inbox.get('sources', []):
        if status.get('name') in feeds:
            report['sources'].append({'name':status['name'], 'status':status['status'] if recent else 'failed',
                'count':int(status.get('count',0)) if recent else 0,
                'detail':daily.text(status.get('detail',''),150) if recent else '本地采集超过 26 小时，等待本机同步'})
    report['news_updated_at'] = inbox['collected_at']
    report['updated_at'] = daily.stamp(now)
    report['published_count'] = sum(map(len,report['items'].values()))
    report['status'] = 'complete' if all(s['status']=='ok' for s in report['sources']) else 'partial'
    daily.atomic_json(report_path, report)
    report_path.with_suffix('.md').write_text(daily.markdown(report),encoding='utf-8')
    daily.manifest(data_dir,daily.load_state(data_dir/'state.json'),now)
    return {'status':'news_imported','count':len(items)}


def sync_news():
    config = read(LOCAL / 'wechat-sources.json', {'feeds':[]})
    items, sources, content = [], [], read(LOCAL/'news-content.json', {})
    now = datetime.now(timezone.utc)
    known = read(ROOT/'config.json')['feeds']
    configured = {f['name']:f for f in config['feeds']}
    for source in known:
        cfg = configured.get(source['name'])
        status = {'name':source['name'],'status':'not_connected','count':0,'detail':'本地订阅服务尚待扫码与账号验证'}
        cooldown = read(LOCAL/'wechat-cooldown.json', {})
        cooling = bool(cooldown.get('until')) and datetime.fromisoformat(cooldown['until']) > now
        if cfg and cooling:
            status.update(status='failed',detail='账号已授权；微信文章接口返回频率限制，本次暂停采集，等待低频补跑')
        elif cfg and cfg.get('url'):
            try:
                # Deliberately private local transport: never export this URL or response headers.
                response = httpx.get(cfg['url'],timeout=30); response.raise_for_status()
                feed = feedparser.parse(response.text)
                if not feed.get('version'): raise ValueError('invalid RSS')
                for e in feed.entries[:40]:
                    t = e.get('published_parsed') or e.get('updated_parsed')
                    if not t: continue
                    when = datetime(*t[:6],tzinfo=timezone.utc)
                    if not now-timedelta(hours=24) <= when <= now: continue
                    item = daily.public_item({'kind':'news','title':e.title,'url':e.link,'source':source['name'],
                        'published_at':when.isoformat(),'summary':e.get('summary','')})
                    items.append(item)
                    body = e.get('content', [{}])[0].get('value') or e.get('summary','')
                    content[item['id']] = html_text(body) or BeautifulSoup(body,'html.parser').get_text(' ',strip=True)
                    status['count'] += 1
                if feed.entries:
                    status.update(status='ok',detail='本机 RSS 已同步；仅筛选最近 24 小时文章')
                else:
                    status.update(status='partial',detail='订阅已配置，文章列表仍未取回；尚不能判断当日更新')
            except (httpx.HTTPError, ValueError, KeyError, AttributeError):
                status.update(status='failed',detail='本地订阅不可用；检查服务与扫码授权')
        sources.append(status)
    inbox = {'schema_version':1,'collected_at':daily.stamp(now),'items':items,'sources':sources}
    daily.atomic_json(LOCAL/'news-content.json',content)
    daily.atomic_json(ROOT/'data'/'news-inbox.json',inbox)
    return import_news(ROOT/'data',now)


def validate_public(data_dir):
    index = read(data_dir/'analyses'/'index.json', {'items':{}})
    entry_fields={'item_id','kind','title','version','requested_version','fingerprint','report_date','status','updated_at','path','message'}
    analysis_fields={'schema_version','item_id','kind','title','url','fingerprint','version','status','model','generated_at','verdict','overview','sections','limitations','checks','sources','recommendation'}
    if set(index)-{'schema_version','updated_at','items'}: raise ValueError('non-public index fields')
    def walk(v):
        if isinstance(v,str): plain(v)
        elif isinstance(v,list):
            for x in v: walk(x)
        elif isinstance(v,dict):
            for k,x in v.items(): plain(k); walk(x)
    walk(index)
    for key,entry in index['items'].items():
        if set(entry)-entry_fields or key!=entry['item_id']+':'+entry['fingerprint']:
            raise ValueError('invalid index entry')
        if entry.get('path'):
            path=Path(entry['path'])
            if path.parent.as_posix()!='data/analyses' or not re.fullmatch(r'item_[0-9a-f]{16}-[0-9a-f]{20}\.json',path.name):
                raise ValueError('invalid analysis path')
            value=read(data_dir/'analyses'/path.name)
            if not value or set(value)-analysis_fields or value['item_id']!=entry['item_id'] or value['fingerprint']!=entry['fingerprint']:
                raise ValueError('invalid analysis identity or fields')
            walk(value)
            if 'recommendation' in value:
                from reading import clean_note
                clean_note(value['recommendation'])
            daily.safe_url(value['url'])
            for src in value['sources']: daily.safe_url(src['url'])
    return {'status':'validated','entries':len(index['items'])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','accept','sync-news','import-news','validate'])
    parser.add_argument('--date',default=datetime.now(daily.TZ).date().isoformat())
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--packet',type=Path); parser.add_argument('--draft',type=Path)
    args=parser.parse_args()
    if args.command=='prepare': result=prepare(args.date,args.refresh)
    elif args.command=='accept': result=accept(args.packet,args.draft)
    elif args.command=='sync-news': result=sync_news()
    elif args.command=='import-news': result=import_news(ROOT/'data')
    else: result=validate_public(ROOT/'data')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__': main()
