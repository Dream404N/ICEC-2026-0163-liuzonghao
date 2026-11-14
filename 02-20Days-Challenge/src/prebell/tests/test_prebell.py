"""纯标准库自检：不联网、不推送、不写 protected 目录（全部用临时目录）。"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/

from prebell import channels, ledger, model, notifier, planner, state as state_store, verify
from prebell import run as runner

HERE = Path(__file__).resolve().parents[1]  # src/prebell/


class PrebellTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.day = datetime.now(model.CST).date().isoformat()
        self.config = json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))
        self.messages = notifier.load_messages()
        self.schedule = self._schedule(self.day)
        self.calls = []

        def fake_sender(title, content):
            self.calls.append((title, content))
            return {"status": "ok", "http_status": 200, "duration_ms": 12,
                    "error": None, "channel": "fake"}

        self.sender = fake_sender

    def tearDown(self):
        self.tmp.cleanup()

    def _schedule(self, day):
        starts = {"P1": "08:40", "P3": "13:30", "P4": "15:10"}
        entries = []
        for period in model.PERIODS:
            for stage in model.STAGES:
                mb = self.config["stages"][stage]["minutes_before"]
                fire = model.fire_at_of(starts[period], mb)
                entries.append({
                    "key": model.make_key(day, period, stage), "date": day,
                    "period": period, "stage": stage, "class_start": starts[period],
                    "fire_at": fire, "course": None,
                })
        return {"entries": entries}

    def _now(self, entry, extra_seconds=9):
        return model.utc_datetime(entry["date"], entry["fire_at"]) + timedelta(seconds=extra_seconds)

    def _call(self, entry, now=None, sender=None):
        return runner.run_once(
            root=self.root, day=entry["date"], period=entry["period"],
            stage=entry["stage"], source="test",
            now_utc=now or self._now(entry), config=self.config,
            schedule=self.schedule, sender=sender or self.sender,
            messages=self.messages,
        )

    def test_key_triplet(self):
        a = model.make_key("2026-11-16", "P1", "depart")
        b = model.make_key("2026-11-16", "P1", "enter")
        self.assertEqual(a, "2026-11-16-P1-depart")
        self.assertNotEqual(a, b)
        with self.assertRaises(ValueError):
            model.make_key("2026-11-16", "P1", "unknown")

    def test_fire_times(self):
        self.assertEqual(model.fire_at_of("08:40", 30), "08:10")
        self.assertEqual(model.fire_at_of("08:40", 5), "08:35")
        self.assertEqual(model.fire_at_of("15:10", 5), "15:05")
        self.assertEqual(model.utc_datetime("2026-11-16", "15:05").strftime("%H:%M"), "07:05")

    def test_planner_build(self):
        data = planner.build()
        keys = [e["key"] for e in data["entries"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(data["count_per_week"], 20)
        self.assertEqual(data["based_on"], "estimated")
        pairs = {}
        for e in data["entries"]:
            pairs.setdefault((e["date"], e["period"]), set()).add(e["stage"])
        self.assertTrue(all(v == set(model.STAGES) for v in pairs.values()))

    def test_templates_hit_keywords(self):
        _, depart = notifier.render("depart", self.schedule["entries"][0], self.messages)
        _, enter = notifier.render("enter", self.schedule["entries"][1], self.messages)
        self.assertIn("准备好东西", depart)
        self.assertIn("可以出发", depart)
        self.assertIn("进入教室", enter)
        self.assertIn(notifier.UNKNOWN_COURSE, depart)

    def test_six_pushes_not_merged(self):
        for entry in self.schedule["entries"]:
            rec = self._call(entry)
            self.assertEqual(rec["result"], "ok", rec["action"])
        self.assertEqual(len(self.calls), 6, "6 条提醒必须各自独立推送，不能合并")
        self.assertEqual(len({c[0] for c in self.calls}), 2, "两套标题都要用到")
        rows = ledger.read_records(self.root, self.day)
        self.assertEqual(len(rows), 6)
        self.assertEqual(len({r["key"] for r in rows}), 6)

    def test_duplicate_not_pushed(self):
        entry = self.schedule["entries"][0]
        self.assertEqual(self._call(entry)["action"], "send")
        second = self._call(entry)
        self.assertEqual(second["action"], "duplicate")
        self.assertEqual(len(self.calls), 1)

    def test_late_skipped(self):
        entry = next(e for e in self.schedule["entries"] if e["stage"] == "depart")
        now = self._now(entry, extra_seconds=12 * 60)
        rec = self._call(entry, now=now)
        self.assertEqual(rec["action"], "skipped_late")
        self.assertTrue(rec["late"])
        self.assertEqual(len(self.calls), 0)

    def test_after_class_skipped(self):
        entry = next(e for e in self.schedule["entries"] if e["stage"] == "enter")
        now = model.utc_datetime(entry["date"], entry["class_start"]) + timedelta(minutes=1)
        rec = self._call(entry, now=now)
        self.assertEqual(rec["action"], "skipped_after_class")
        self.assertEqual(len(self.calls), 0)

    def test_failure_recorded_and_scrubbed(self):
        def bad_sender(title, content):
            return {"status": "failed", "http_status": 500, "duration_ms": 30,
                    "error": "POST https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRET123 failed",
                    "channel": "wecom_webhook"}

        rec = self._call(self.schedule["entries"][0], sender=bad_sender)
        self.assertEqual(rec["result"], "error")
        self.assertIsNotNone(rec["error"])
        text = ledger.log_path(self.root, self.day).read_text(encoding="utf-8")
        self.assertNotIn("SECRET123", text)
        self.assertIn("[url]", text)

    def test_hash_chain_and_verify_all_green(self):
        for entry in self.schedule["entries"]:
            self._call(entry)
        rows = ledger.read_records(self.root, self.day)
        prev = "genesis"
        for r in rows:
            self.assertEqual(r["prev_hash"], prev)
            self.assertEqual(r["hash"], ledger.chain_hash(prev, r))
            prev = r["hash"]
        ledger.rollup(self.root, self.day, expected=len(self.schedule["entries"]))
        report = verify.verify_day(self.root, self.day, self.schedule)
        self.assertTrue(report["all_ok"], report)

    def test_personal_tokens_scrubbed(self):
        self.assertNotIn("SPT_abc123XYZ", model.scrub_text("spt=SPT_abc123XYZ"))
        self.assertIn("[token]", model.scrub_text("SPT_abc123XYZ"))
        self.assertNotIn("AT_secret999", model.scrub_text("AT_secret999"))

    def test_wxpusher_personal_payload(self):
        captured = {}

        class Resp:
            status = 200

            def read(self):
                return b'{"code":1000,"msg":"ok","success":true}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_open(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return Resp()

        with mock.patch.dict(os.environ, {"PREBELL_WXPUSHER_SPT": "SPT_testtoken"}):
            with mock.patch("urllib.request.urlopen", fake_open):
                res = channels.send_wxpusher("标题", "正文", self.config)
        self.assertEqual(res["status"], "ok", res)
        self.assertEqual(res["channel"], "wxpusher_spt")
        self.assertIn("simple-push", captured["url"])
        self.assertEqual(captured["body"]["spt"], "SPT_testtoken")
        self.assertEqual(captured["body"]["contentType"], 1)
        self.assertIn("标题", captured["body"]["content"])

    def test_primary_quota_falls_back_to_personal_channel(self):
        cfg = dict(self.config)
        cfg["primary"] = {"type": "serverchan_turbo", "env_var": "PREBELL_SENDKEY"}
        cfg["fallback"] = {"type": "wxpusher_spt", "env_var": "PREBELL_WXPUSHER_SPT"}
        cfg["fallback_channel_enabled"] = True
        seen = []

        def fake(kind, status):
            def f(title, content, config, timeout=10):
                seen.append(kind)
                return {"status": status, "http_status": 200, "duration_ms": 1,
                        "error": "quota" if status == "failed" else None,
                        "channel": kind}
            return f

        with mock.patch.object(channels, "send_serverchan", fake("serverchan_turbo", "failed")), \
             mock.patch.object(channels, "send_wxpusher", fake("wxpusher_spt", "ok")):
            res = channels.build_sender(cfg)("标题", "正文")
        self.assertEqual(seen, ["serverchan_turbo", "wxpusher_spt"])
        self.assertEqual(res["status"], "ok")
        self.assertNotEqual(res["channel"], "wecom_webhook")


if __name__ == "__main__":
    unittest.main(verbosity=2)
