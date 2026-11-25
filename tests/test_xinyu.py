"""心语离线单测:不联网、不花 token。"""

from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from xinyu import agent, cli, mock, tools, web
from xinyu.db import Database

SAMPLE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "entries-sample.json")


def load_sample() -> list[dict]:
    with open(SAMPLE, encoding="utf-8") as f:
        return json.load(f)


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(os.path.join(self.tmp.name, "t.db"))
        for e in load_sample():
            self.db.save_entry(e["date"], e["text"])

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()


class TestTextLayer(unittest.TestCase):
    def test_mood_score_positive(self):
        self.assertGreater(tools.mood_score("今天挺顺利,很满足"), 0)

    def test_mood_score_negative_and_clamped(self):
        self.assertEqual(tools.mood_score("崩溃 崩溃 崩溃 崩溃"), -5)

    def test_mood_label(self):
        self.assertEqual(tools.mood_label(-4), "低落")

    def test_stressors_with_evidence(self):
        ss = tools.stressors("明天面试,焦虑得睡不着")
        labels = [s["label"] for s in ss]
        self.assertIn("求职压力", labels)
        self.assertTrue(next(s for s in ss if s["label"] == "求职压力")["evidence"])

    def test_advice_for_low_mood(self):
        adv = tools.advice_for(-4, ["睡眠问题"])
        self.assertTrue(any("屏幕" in a for a in adv))


class TestTrend(unittest.TestCase):
    def test_trend_arithmetic(self):
        es = [{"date": "2026-11-20", "mood": "低落", "score": -4},
              {"date": "2026-11-21", "mood": "低落", "score": -3},
              {"date": "2026-11-22", "mood": "还行", "score": 1}]
        t = tools.trend(es)
        self.assertEqual(t["days"], 3)
        self.assertEqual(t["avg"], -2.0)
        self.assertEqual(t["low_runs"], 2)
        self.assertEqual(t["worst"]["score"], -4)

    def test_trend_empty(self):
        self.assertEqual(tools.trend([])["analyzed"], 0)


class TestDb(BaseCase):
    def test_same_date_overwrites(self):
        before = len(self.db.list_entries(50))
        self.db.save_entry("2026-11-24", "改口了,今天其实不太好")
        self.assertEqual(len(self.db.list_entries(50)), before)
        self.assertIn("改口", self.db.get_entry("2026-11-24")["text"])

    def test_set_analysis_and_recent_order(self):
        e = self.db.get_entry("2026-11-24")
        self.db.set_analysis(e["id"], "轻松", 3, ["睡眠问题"], "早点睡")
        got = self.db.get_entry("2026-11-24")
        self.assertEqual(got["score"], 3)
        self.assertEqual(got["stressors"], ["睡眠问题"])
        dates = [x["date"] for x in self.db.recent(7)]
        self.assertEqual(dates, sorted(dates))

    def test_delete_entry(self):
        e = self.db.get_entry("2026-11-18")
        self.assertTrue(self.db.delete_entry(e["id"]))


class TestOfflineAnalysis(BaseCase):
    def test_mock_analyze_marks_offline(self):
        r = mock.analyze(self.db.get_entry("2026-11-21"))
        self.assertTrue(r["offline"])
        self.assertLess(r["score"], 0)
        self.assertTrue(r["stressors"])

    def test_verify_drops_unverifiable_evidence(self):
        entry = {"date": "2026-11-24", "text": "面试完了,轻松很多。"}
        data = {"mood": "轻松", "score": 3,
                "stressors": [{"label": "求职压力", "evidence": "面试完了,轻松很多。"},
                              {"label": "瞎编", "evidence": "原文根本没有这句"}],
                "advice": ["记下来今天做了什么"]}
        result, problems = agent.verify(entry, data)
        self.assertEqual(len(result["stressors"]), 1)
        self.assertEqual(len(problems), 1)

    def test_verify_clamps_score(self):
        entry = {"date": "2026-11-24", "text": "还行"}
        result, problems = agent.verify(entry, {"mood": "x", "score": 12})
        self.assertEqual(result["score"], 5)
        self.assertTrue(problems)

    def test_trend_offline_summary(self):
        es = self.db.recent(7)
        r = agent.trend(es, force_mock=True)
        self.assertTrue(r["offline"])
        self.assertIn("天", r["summary"])


class TestCli(BaseCase):
    def _run(self, argv, db_path):
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["--db", db_path] + argv)
        return buf.getvalue()

    def test_add_analyze_trend(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_path = os.path.join(tmp.name, "c.db")
        f = os.path.join(tmp.name, "e.txt")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(load_sample()[0]["text"])
        self.assertIn("已记录", self._run(["add", f, "--date", "2026-11-25"], db_path))
        out = self._run(["--mock", "analyze", "2026-11-25"], db_path)
        self.assertIn("离线模式", out)
        self.assertIn("趋势", self._run(["--mock", "trend", "--days", "7"], db_path))
        tmp.cleanup()


class TestWeb(BaseCase):
    def test_api_day_and_trend(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), web._make_handler(self.db, {"api_key": ""}, True))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_address[1]
        try:
            body = json.dumps({"date": "2026-11-25", "text": "今天有点累,加班到九点"}).encode("utf-8")
            req = Request(f"http://127.0.0.1:{port}/api/day", data=body,
                          headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req, timeout=15) as resp:
                r = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(r["offline"])
            self.assertLessEqual(r["score"], 0)
            with urlopen(f"http://127.0.0.1:{port}/api/trend?days=7", timeout=10) as resp:
                t = json.loads(resp.read().decode("utf-8"))
            self.assertIn("avg", t)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
