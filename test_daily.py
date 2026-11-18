import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import daily

NOW = datetime(2026, 11, 18, 1, tzinfo=timezone.utc)


def item(**extra):
    return {"kind": "paper", "title": "Memory poisoning in LLM agents", "url": "https://arxiv.org/abs/2601.12345v1", "source": "arXiv", "summary": "Memory poisoning and authorization", **extra}


class PublicDigestTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((daily.ROOT / "config.json").read_text(encoding="utf-8"))
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name) / "data"

    def tearDown(self):
        self.temp.cleanup()

    def test_private_fields_never_pass_through(self):
        value = daily.public_item(item(metadata={"workbook_notes": "PRIVATE SENTINEL"}, api_key="SECRET SENTINEL", idea="PRIVATE IDEA"))
        encoded = json.dumps(value)
        self.assertNotIn("PRIVATE", encoded)
        self.assertNotIn("SECRET", encoded)
        self.assertNotIn("metadata", value)

    def test_credential_urls_rejected(self):
        for url in ["file:///C:/private", "javascript:alert(1)", "https://user:pass@example.org", "https://example.org?token=secret"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                daily.safe_url(url)

    def test_html_is_text_only(self):
        result = daily.public_item(item(title='<img src=x onerror="alert(1)">Safe title', summary="<script>bad()</script><b>real text</b>"))
        self.assertEqual(result["title"], "Safe title")
        self.assertNotIn("<", result["summary"])

    def test_arxiv_versions_keep_identity(self):
        state = daily.empty_state()
        a = daily.merge_item(state, item(version="v1"), NOW)
        b = daily.merge_item(state, item(url="https://arxiv.org/html/2601.12345v2", version="v2"), NOW + timedelta(hours=1))
        self.assertEqual(a, b)
        self.assertEqual(len(state["items"]), 1)
        self.assertEqual(state["items"][a]["change"], "version_updated")
        self.assertEqual(state["items"][a]["first_seen"], daily.stamp(NOW))

    def test_bad_atom_not_empty_success(self):
        with self.assertRaises(daily.FetchFailure):
            daily.arxiv_items("<html>access denied</html>")

    def test_dates_and_version_distinct(self):
        atom = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>https://arxiv.org/abs/2601.12345v2</id><title>Memory poisoning</title><summary>test</summary><published>2026-01-01T00:00:00Z</published><updated>2026-11-18T00:00:00Z</updated></entry></feed>'''
        record = daily.arxiv_items(atom)[0]
        self.assertNotEqual(record["published_at"], record["updated_at"])
        self.assertEqual(record["version"], "v2")

    def test_cold_start_is_not_zero(self):
        value = daily.growth([{"at": daily.stamp(NOW), "count": 10}], 1, NOW)
        self.assertIsNone(value["delta"])

    def test_unstars_can_be_negative(self):
        value = daily.growth([{"at": daily.stamp(NOW-timedelta(days=1)), "count": 12}, {"at": daily.stamp(NOW), "count": 10}], 1, NOW)
        self.assertEqual(value["delta"], -2)
        self.assertEqual(value["status"], "complete")

    def test_gap_not_daily_growth(self):
        value = daily.growth([{"at": daily.stamp(NOW-timedelta(days=3)), "count": 8}, {"at": daily.stamp(NOW), "count": 10}], 1, NOW)
        self.assertEqual(value["status"], "irregular_window")
        self.assertEqual(value["days"], 3)

    def test_unrelated_memory_project_not_recommended(self):
        record = daily.public_item(item(kind="repo", title="Memory allocation utility", url="https://github.com/test/allocator", summary="Memory allocator", stars=10000))
        self.assertIsNone(daily.rank(record, self.config))

    def test_partial_and_not_connected_visible(self):
        state = daily.empty_state()
        key = daily.merge_item(state, item(), NOW)
        report = daily.make_report(self.config, state, [{"name":"arXiv", "status":"ok", "count":1, "detail":""}, {"name":"量子位", "status":"not_connected", "count":0, "detail":"awaiting RSS"}], [key], NOW)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["items"]["news"], [])

    def test_all_failure_preserves_previous_report(self):
        state = daily.empty_state()
        key = daily.merge_item(state, item(), NOW)
        good = [{"name":"arXiv", "status":"ok", "count":1, "detail":""}]
        with patch.object(daily, "collect", return_value=(good, [key])), patch.object(daily, "load_state", return_value=state):
            daily.run_daily(self.config, self.data, now=NOW, web=object())
        before = (self.data / "reports/2026-11-18.json").read_bytes()
        failed = [{"name":"arXiv", "status":"failed", "count":0, "detail":"timeout"}]
        with patch.object(daily, "collect", return_value=(failed, [])):
            result = daily.run_daily(self.config, self.data, now=NOW+timedelta(hours=1), web=object(), force=True)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(before, (self.data / "reports/2026-11-18.json").read_bytes())
        manifest = json.loads((self.data / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["latest_attempt"]["status"], "failed")

    def test_failed_first_run_has_no_fake_report(self):
        failed = [{"name":"arXiv", "status":"failed", "count":0, "detail":"timeout"}]
        with patch.object(daily, "collect", return_value=(failed, [])):
            daily.run_daily(self.config, self.data, now=NOW, web=object())
        manifest = json.loads((self.data / "manifest.json").read_text(encoding="utf-8"))
        self.assertIsNone(manifest["latest"])
        self.assertFalse((self.data / "reports/2026-11-18.json").exists())

    def test_same_day_idempotency(self):
        statuses = [{"name":"arXiv", "status":"ok", "count":0, "detail":""}, {"name":"量子位", "status":"not_connected", "count":0, "detail":""}]
        with patch.object(daily, "collect", return_value=(statuses, [])) as collector:
            daily.run_daily(self.config, self.data, now=NOW, web=object())
            result = daily.run_daily(self.config, self.data, now=NOW+timedelta(hours=2), web=object())
        self.assertEqual(collector.call_count, 1)
        self.assertEqual(result["status"], "skipped")

    def test_day_changes_at_beijing_midnight(self):
        next_day = datetime(2026, 11, 18, 16, tzinfo=timezone.utc)
        failed = [{"name":"source", "status":"failed", "count":0, "detail":""}]
        with patch.object(daily, "collect", return_value=(failed, [])):
            result = daily.run_daily(self.config, self.data, now=next_day, web=object())
        self.assertEqual(result["date"], "2026-11-19")

    def test_private_state_rejected(self):
        self.data.mkdir()
        state = daily.empty_state(); state["ideas"] = ["private"]
        daily.atomic_json(self.data / "state.json", state)
        with self.assertRaises(ValueError):
            daily.load_state(self.data / "state.json")

    def test_real_collector_all_sources_failing_is_not_success(self):
        class FailedWeb:
            def get(self, *args, **kwargs):
                raise daily.FetchFailure("offline")
        state = daily.empty_state()
        statuses, ids = daily.collect(self.config, state, FailedWeb(), NOW)
        self.assertEqual(ids, [])
        self.assertEqual(daily.make_report(self.config, state, statuses, ids, NOW)["status"], "failed")
        self.assertTrue(any(s["status"] == "not_connected" for s in statuses))

    def test_authenticated_private_repositories_never_published(self):
        class Response:
            def __init__(self, payload): self.payload = payload
            def json(self): return self.payload
        class PrivateWeb:
            queries = []
            def get(self, url, **kwargs):
                if 'arxiv.org' in url:
                    raise daily.FetchFailure('unavailable')
                if url.endswith('/search/repositories'):
                    self.queries.append(kwargs['params']['q'])
                    return Response({'items': []})
                return Response({'private': True, 'visibility': 'private', 'full_name': 'private/research', 'html_url': 'https://github.com/private/research', 'stargazers_count': 0})
        web = PrivateWeb(); state = daily.empty_state()
        statuses, ids = daily.collect(self.config, state, web, NOW)
        self.assertEqual(state['items'], {})
        self.assertEqual(ids, [])
        self.assertTrue(all('is:public' in q for q in web.queries))

    def test_build_excludes_state_and_non_public_files(self):
        self.data.mkdir(); (self.data / "reports").mkdir()
        daily.atomic_json(self.data / "manifest.json", {"archive":[], "latest":None})
        daily.atomic_json(self.data / "state.json", daily.empty_state())
        (self.data / "private.txt").write_text("PRIVATE", encoding="utf-8")
        output = Path(self.temp.name) / "dist"
        daily.build(self.data, output)
        self.assertTrue((output / "index.html").exists())
        self.assertFalse((output / "data/state.json").exists())
        self.assertFalse((output / "data/private.txt").exists())

    def test_weekly_has_only_public_dynamic_content(self):
        statuses = [{"name":"arXiv", "status":"ok", "count":0, "detail":""}]
        with patch.object(daily, "collect", return_value=(statuses, [])):
            daily.run_daily(self.config, self.data, now=NOW, web=object())
        daily.run_weekly(self.data, NOW)
        weekly = json.loads((self.data / "weekly/2026-11-18.json").read_text(encoding="utf-8"))
        self.assertEqual(weekly["days_with_reports"], 1)
        self.assertEqual(set(weekly["items"]), {"paper", "repo", "news"})


if __name__ == "__main__":
    unittest.main()

