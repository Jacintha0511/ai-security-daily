"""Public-only, deterministic research digest. No model or private database access."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import feedparser
import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Shanghai")
ITEM_FIELDS = {"id", "kind", "title", "url", "source", "summary", "published_at", "updated_at", "version", "first_seen", "last_seen", "stars", "topics", "reason", "priority", "selection_basis", "score", "day_growth", "week_growth", "change"}
STATE_FIELDS = {"schema_version", "items", "stars", "cursors", "last_success", "runs", "latest_attempt"}
PUBLIC_SOURCE_NAMES = {"arXiv", "GitHub"}


def stamp(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def text(value, limit=600):
    return re.sub(r"\s+", " ", BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)).strip()[:limit]


def safe_url(url):
    p = urlsplit(str(url).strip())
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
        raise ValueError("invalid public URL")
    if any(k.lower() in {"token", "key", "api_key", "access_token", "xsec_token", "password", "authorization", "signature"} for k, _ in parse_qsl(p.query)):
        raise ValueError("credential-bearing URL is not publishable")
    return urlunsplit(("https", p.netloc.lower(), p.path, urlencode([(k, v) for k, v in parse_qsl(p.query) if not k.startswith("utm_")]), ""))


def canonical(url):
    url = safe_url(url)
    p = urlsplit(url)
    if p.hostname in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
        key = re.sub(r"v\d+$", "", p.path.split("/")[-1].removesuffix(".pdf"))
        return "https://arxiv.org/abs/" + key
    if p.hostname in {"github.com", "www.github.com"}:
        return "https://github.com/" + "/".join(p.path.strip("/").split("/")[:2]).removesuffix(".git").lower()
    return url.rstrip("/")


def public_item(raw):
    """Construct from allowlisted public fields; never pass through private metadata."""
    if raw.get("kind") not in {"paper", "repo", "news"}:
        raise ValueError("not a public dynamic item")
    url = canonical(raw["url"])
    out = {"id": "item_" + hashlib.sha256(url.encode()).hexdigest()[:16],
           "kind": raw["kind"], "url": url, "title": text(raw.get("title"), 350),
           "source": text(raw.get("source"), 80), "summary": text(raw.get("summary"), 450)}
    for name in ("published_at", "updated_at", "version", "first_seen", "last_seen"):
        if raw.get(name):
            out[name] = str(raw[name])[:60]
    if raw.get("kind") == "repo":
        out["stars"] = max(0, int(raw.get("stars", 0)))
        out["topics"] = [text(t, 60) for t in raw.get("topics", [])[:20]]
    return out


def empty_state():
    return {"schema_version": 1, "items": {}, "stars": {}, "cursors": {}, "runs": [], "last_success": None, "latest_attempt": None}


def load_state(path):
    if not path.exists():
        return empty_state()
    state = json.loads(path.read_text(encoding="utf-8"))
    if set(state) - STATE_FIELDS:
        raise ValueError("state contains non-public fields")
    for item in state.get("items", {}).values():
        if set(item) - ITEM_FIELDS:
            raise ValueError("item contains non-public fields")
    return {**empty_state(), **state}


def merge_item(state, raw, now):
    item = public_item(raw)
    key = item["id"]
    prior = state["items"].get(key, {})
    item["first_seen"] = prior.get("first_seen", stamp(now))
    item["last_seen"] = stamp(now)
    if prior and item.get("version") and prior.get("version") != item["version"]:
        item["change"] = "version_updated"
    else:
        item["change"] = "newly_discovered" if not prior else "observed_again"
    state["items"][key] = item
    if item["kind"] == "repo":
        snapshots = state["stars"].setdefault(key, [])
        snapshots[:] = [s for s in snapshots if s["at"] != stamp(now)]
        snapshots.append({"at": stamp(now), "count": item["stars"]})
        cutoff = now - timedelta(days=45)
        snapshots[:] = sorted((s for s in snapshots if datetime.fromisoformat(s["at"]) >= cutoff), key=lambda s: s["at"])
    return key


def growth(snapshots, days, now):
    ordered = sorted((s for s in snapshots if datetime.fromisoformat(s["at"]) <= now), key=lambda s: s["at"])
    before = [s for s in ordered if datetime.fromisoformat(s["at"]) <= now - timedelta(days=days)]
    if not before or not ordered:
        return {"delta": None, "status": "insufficient_history"}
    a, b = before[-1], ordered[-1]
    span = (datetime.fromisoformat(b["at"]) - datetime.fromisoformat(a["at"])).total_seconds() / 86400
    fresh = (now - datetime.fromisoformat(b["at"])).total_seconds() <= 10800
    return {"delta": b["count"] - a["count"], "days": round(span, 2),
            "status": "complete" if abs(span - days) <= 0.125 and fresh else "irregular_window"}


def rank(item, config):
    content = (item["title"] + " " + item["summary"] + " " + " ".join(item.get("topics", []))).lower()
    hits = [k for k in config["keywords"] if k.lower() in content]
    focus = [k for k in config["focus"] if k.lower() in content]
    seed = item["kind"] == "repo" and item["url"].split("github.com/")[-1].lower() in {s.lower() for s in config["seed_repos"]}
    if not hits and not seed:
        return None
    score = len(hits) * 3 + len(focus) * 4 + (5 if seed else 0)
    return {**item, "score": score, "reason": "研究主题匹配：" + "、".join(dict.fromkeys(hits + focus)) if hits or focus else "已登记的安全研究基准／防御项目",
            "priority": "建议精读" if item["kind"] == "paper" and focus else "快速浏览",
            "selection_basis": "规则预筛；不是模型精排或学术质量评分"}


class FetchFailure(RuntimeError):
    pass


class Web:
    def __init__(self):
        self.client = httpx.Client(timeout=25, follow_redirects=True, headers={"User-Agent": "ai-security-daily/1.0 (+https://github.com/Jacintha0511/ai-security-daily)"})
        self.last_arxiv = 0.0

    def get(self, url, **kwargs):
        if "arxiv.org" in urlsplit(url).hostname:
            time.sleep(max(0, 3.1 - (time.monotonic() - self.last_arxiv)))
            self.last_arxiv = time.monotonic()
        for attempt in range(2):
            try:
                response = self.client.get(safe_url(url), **kwargs)
                response.raise_for_status()
                if len(response.content) > 8_000_000:
                    raise FetchFailure("响应超过大小上限")
                return response
            except httpx.HTTPError as exc:
                code = getattr(getattr(exc, "response", None), "status_code", None)
                if code in {401, 403, 404, 429} or attempt:
                    raise FetchFailure(f"HTTP {code or '连接失败'}") from None
                time.sleep(1)


def arxiv_items(content):
    feed = feedparser.parse(content)
    if not feed.get("version") or (feed.get("bozo") and not feed.entries):
        raise FetchFailure("arXiv Atom 无效")
    result = []
    for entry in feed.entries:
        if entry.get("title", "").lower() == "error":
            raise FetchFailure("arXiv 查询错误")
        match = re.search(r"v\d+$", entry.id)
        result.append({"kind": "paper", "title": entry.title, "url": entry.id, "source": "arXiv",
                       "summary": entry.get("summary", ""), "published_at": entry.get("published"),
                       "updated_at": entry.get("updated"), "version": match[0] if match else ""})
    return result


def collect(config, state, web, now):
    statuses, collected = [], set()
    since = now - timedelta(days=config["lookback_days"])
    prior = state["cursors"].get("arxiv")
    if prior:
        since = min(since, datetime.fromisoformat(prior) - timedelta(days=1))
    count, saturated = 0, False
    try:
        size = config["arxiv_page_size"]
        for page in range(config["arxiv_pages"]):
            parsed = arxiv_items(web.get("https://export.arxiv.org/api/query", params={
                "search_query": config["arxiv_query"], "start": page * size, "max_results": size,
                "sortBy": "lastUpdatedDate", "sortOrder": "descending"}).text)
            recent = [i for i in parsed if not i.get("updated_at") or datetime.fromisoformat(i["updated_at"]) >= since]
            for item in recent:
                collected.add(merge_item(state, item, now)); count += 1
            saturated = len(parsed) == size and len(recent) == len(parsed)
            if not saturated:
                break
        statuses.append({"name": "arXiv", "status": "partial" if saturated else "ok", "count": count,
                         "detail": "已达分页上限，覆盖可能不完整" if saturated else "包含新论文与版本更新；预印本不等于正式发表"})
        if not saturated:
            state["cursors"]["arxiv"] = stamp(now)
    except (FetchFailure, KeyError, ValueError) as exc:
        statuses.append({"name": "arXiv", "status": "failed", "count": count, "detail": str(exc)[:120]})

    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    discovered, errors = {}, 0
    for query in config["github_queries"]:
        try:
            response = web.get("https://api.github.com/search/repositories", headers=headers,
                               params={"q": query + " is:public", "sort": "updated", "per_page": 10}).json()
            discovered.update({r["full_name"].lower(): r for r in response["items"]})
            statuses.append({"name": "GitHub 发现：" + query.split(" in:")[0], "status": "partial" if response.get("incomplete_results") else "ok", "count": len(response["items"]), "detail": "候选发现，不是全站升星榜"})
        except (FetchFailure, KeyError, ValueError):
            errors += 1
            statuses.append({"name": "GitHub 发现：" + query.split(" in:")[0], "status": "failed", "count": 0, "detail": "搜索不可用或被限流"})
    tracked = sorted((i for i in state["items"].values() if i["kind"] == "repo"), key=lambda i: i.get("last_seen", ""))
    names = list(dict.fromkeys(name.lower() for name in config["seed_repos"] + list(discovered) + [i["url"].split("github.com/")[-1] for i in tracked]))[:config["max_repos"]]
    count = 0
    for name in names:
        try:
            repo = discovered.get(name.lower()) or web.get("https://api.github.com/repos/" + name, headers=headers).json()
            if repo.get("private") is not False or repo.get("visibility", "public") != "public":
                errors += 1
                continue
            if repo.get("archived"):
                continue
            raw = {"kind": "repo", "title": repo["full_name"], "url": repo["html_url"], "source": "GitHub",
                   "summary": repo.get("description", ""), "stars": repo["stargazers_count"],
                   "topics": repo.get("topics", []), "published_at": repo.get("created_at"), "updated_at": repo.get("pushed_at")}
            collected.add(merge_item(state, raw, now)); count += 1
        except (FetchFailure, KeyError, ValueError):
            errors += 1
    statuses.append({"name": "GitHub 快照", "status": "failed" if count == 0 else "partial" if errors else "ok",
                     "count": count, "detail": f"本轮记录 {count} 个项目；跟踪池有限，失败或限流={errors}"})
    for source in config["feeds"]:
        if not source.get("url"):
            statuses.append({"name": source["name"], "status": "not_connected", "count": 0, "detail": "待接入可用 RSS，不代表今天没有报道"})
            continue
        try:
            feed = feedparser.parse(web.get(source["url"]).text)
            if not feed.get("version"):
                raise FetchFailure("RSS 无效")
            count = 0
            for entry in feed.entries[:30]:
                published_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
                published = datetime(*published_tuple[:6], tzinfo=timezone.utc).isoformat() if published_tuple else None
                if published and datetime.fromisoformat(published) < since:
                    continue
                collected.add(merge_item(state, {"kind": "news", "title": entry.title, "url": entry.link, "source": source["name"], "summary": entry.get("summary", ""), "published_at": published}, now))
                count += 1
            statuses.append({"name": source["name"], "status": "ok", "count": count, "detail": "RSS 摘要，非全文核验"})
        except (FetchFailure, KeyError, ValueError, AttributeError):
            statuses.append({"name": source["name"], "status": "failed", "count": 0, "detail": "RSS 采集失败"})
    return statuses, sorted(collected)


def make_report(config, state, statuses, ids, now):
    actual = [s for s in statuses if s["status"] != "not_connected"]
    success = any(s["status"] in {"ok", "partial"} for s in actual)
    partial = any(s["status"] != "ok" for s in statuses)
    status = "failed" if not success else "partial" if partial else "complete"
    ranked = [r for i in ids if (r := rank(state["items"][i], config))]
    ranked.sort(key=lambda i: (-i["score"], -i.get("stars", 0), i["id"]))
    selections = {kind: [i for i in ranked if i["kind"] == kind][:limit] for kind, limit in config["limits"].items()}
    repos = []
    for item in state["items"].values():
        if item["kind"] != "repo" or not rank(item, config):
            continue
        repos.append({**item, "day_growth": growth(state["stars"].get(item["id"], []), 1, now),
                      "week_growth": growth(state["stars"].get(item["id"], []), 7, now)})
    repos.sort(key=lambda i: (i["day_growth"]["status"] == "complete", i["day_growth"].get("delta") or 0, i.get("stars", 0)), reverse=True)
    return {"schema_version": 1, "date": now.astimezone(TZ).date().isoformat(), "generated_at": stamp(now),
            "status": status, "selection_basis": "规则预筛", "sources": statuses, "items": selections,
            "repo_growth": repos[:20], "candidate_count": len(set(ids)), "published_count": sum(map(len, selections.values())),
            "run_url": os.environ.get("GITHUB_SERVER_URL", "https://github.com") + "/" + os.environ.get("GITHUB_REPOSITORY", "Jacintha0511/ai-security-daily") + "/actions/runs/" + os.environ.get("GITHUB_RUN_ID", "") if os.environ.get("GITHUB_RUN_ID") else None,
            "notes": ["仅公开论文、项目、报道；不包含私人 idea 或实验。", "首次发现时间不等于发表时间；摘要与规则匹配不代表精读。", "star 为快照净变化，取消 star 可产生负值。"]}


def markdown(report):
    lines = [f"# AI 安全动态日报 · {report['date']}", "", f"状态：{report['status']} · {report['selection_basis']} · {report['generated_at']}", ""]
    for kind, label in [("paper", "论文"), ("repo", "开源项目"), ("news", "报道")]:
        lines += ["## " + label, ""]
        for item in report["items"][kind]:
            lines += [f"### [{item['title']}]({item['url']})", "", item["summary"], "", item["reason"], ""]
        if not report["items"][kind]:
            lines += ["本次没有可推荐条目，请结合来源状态判断。", ""]
    lines += ["## 来源状态", ""]
    lines += [f"- {s['name']}：{s['status']}，{s['count']} 条。{s['detail']}" for s in report["sources"]]
    return "\n".join(lines) + "\n"


def manifest(data_dir, state, now):
    archive = []
    for path in sorted((data_dir / "reports").glob("*.json"), reverse=True):
        report = json.loads(path.read_text(encoding="utf-8"))
        archive.append({"date": report["date"], "status": report["status"], "generated_at": report["generated_at"],
                        "count": report["published_count"], "path": "data/reports/" + path.name})
    weekly = [{"date": p.stem, "path": "data/weekly/" + p.name} for p in sorted((data_dir / "weekly").glob("*.json"), reverse=True)]
    value = {"schema_version": 1, "updated_at": stamp(now), "timezone": "Asia/Shanghai", "latest": archive[0] if archive else None,
             "archive": archive, "weekly": weekly, "latest_attempt": state["latest_attempt"],
             "schedule": "云端 01:15 采集、01:45/08:15/10:15 检查；本机 Codex 02:00 解析、03:45 补跑；周日 09:15 周报（北京时间）",
             "privacy": "公开动态站；私人 idea、阅读笔记和实验数据仅保留本地", "model": "未调用模型 · 规则预筛"}
    atomic_json(data_dir / "manifest.json", value)


def run_daily(config, data_dir, *, force=False, web=None, now=None):
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(TZ).date().isoformat()
    state_path = data_dir / "state.json"
    state = load_state(state_path)
    report_path = data_dir / "reports" / (today + ".json")
    if report_path.exists() and not force:
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        # Missing subscriptions are not transient errors; don't recollect everything for them.
        if previous["status"] != "failed" and all(s["status"] in {"ok", "not_connected"} for s in previous["sources"]):
            manifest(data_dir, state, now)
            return {"status": "skipped", "date": today}
    own_web = web is None
    web = web or Web()
    try:
        statuses, ids = collect(config, state, web, now)
    finally:
        if own_web:
            web.client.close()
    report = make_report(config, state, statuses, ids, now)
    attempt = {k: report[k] for k in ("date", "generated_at", "status", "sources", "candidate_count", "run_url")}
    state["latest_attempt"] = attempt
    state["runs"] = (state["runs"] + [attempt])[-90:]
    if report["status"] != "failed":
        state["last_success"] = stamp(now)
        atomic_json(report_path, report)
        report_path.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    # Total failure never overwrites a previously usable report.
    atomic_json(state_path, state)
    manifest(data_dir, state, now)
    return {"date": today, "status": report["status"], "candidates": len(ids), "published": report["published_count"]}


def run_weekly(data_dir, now=None):
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(TZ).date()
    start = day - timedelta(days=6)
    reports = []
    for path in sorted((data_dir / "reports").glob("*.json")):
        if start.isoformat() <= path.stem <= day.isoformat():
            reports.append(json.loads(path.read_text(encoding="utf-8")))
    unique = {kind: {} for kind in ("paper", "repo", "news")}
    for report in reports:
        for kind in unique:
            for item in report["items"][kind]:
                unique[kind][item["id"]] = item
    value = {"date": day.isoformat(), "start": start.isoformat(), "generated_at": stamp(now), "days_with_reports": len(reports),
             "items": {k: list(v.values()) for k, v in unique.items()}, "sources": reports[-1]["sources"] if reports else [],
             "repo_growth": reports[-1]["repo_growth"] if reports else [], "selection_basis": "七日公开动态汇总，非私人科研进度"}
    atomic_json(data_dir / "weekly" / (day.isoformat() + ".json"), value)
    manifest(data_dir, load_state(data_dir / "state.json"), now)


def build(data_dir, destination):
    # Only explicit website assets and public report JSON are ever deployed.
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "styles.css", "app.js", "analysis.html", "analysis.js", "analysis.css"):
        if not (ROOT / 'site' / name).exists():
            continue
        shutil.copy2(ROOT / "site" / name, destination / name)
    target = destination / "data"
    target.mkdir(exist_ok=True)
    shutil.copy2(data_dir / "manifest.json", target / "manifest.json")
    for folder in ("reports", "weekly"):
        (target / folder).mkdir(exist_ok=True)
        for path in (data_dir / folder).glob("*.json"):
            shutil.copy2(path, target / folder / path.name)
    from enrich import validate_public
    validate_public(data_dir)
    analysis_dir = data_dir / 'analyses'
    if analysis_dir.exists():
        (target / 'analyses').mkdir(exist_ok=True)
        for path in analysis_dir.glob('*.json'):
            shutil.copy2(path, target / 'analyses' / path.name)
    (destination / ".nojekyll").write_text("", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["daily", "weekly", "build"])
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "daily":
        result = run_daily(json.loads(args.config.read_text(encoding="utf-8")), args.data_dir, force=args.force)
    elif args.command == "weekly":
        run_weekly(args.data_dir); result = {"status": "weekly_generated"}
    else:
        build(args.data_dir, args.output); result = {"status": "built", "directory": str(args.output)}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

