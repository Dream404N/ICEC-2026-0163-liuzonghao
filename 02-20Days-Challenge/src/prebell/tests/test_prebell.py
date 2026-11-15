"""纯标准库自检：不联网、不真推送、不写 protected 目录（全部用临时目录）。"""
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/

from prebell import channels, ledger, model, notifier, planner, state as state_store, verify
from prebell import run as runner

HERE = Path(__file__).resolve().parents[1]  # src/prebell/
DAY = "2026-11-16"  # 第 11 周周一，三大节都有课


class PrebellTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))
        self.messages = notifier.load_messages()
        self.schedule = planner.build()
        self.calls = []

        def fake_sender(title, content):
            self.calls.append((title, content))
            return {"status": "ok", "http_status": 200, "duration_ms": 12,
                    "error": None, "channel": "fake"}

        self.sender = fake_sender

    def tearDown(self):
        self.tmp.cleanup()

    def entries_of(self, day=DAY):
        return [e for e in self.schedule["entries"] if e["date"] == day]

    def now_at(self, entry, extra_seconds=9):
        return model.utc_datetime(entry["date"], entry["remind_at"]) + timedelta(seconds=extra_seconds)

    def call(self, entry, now=None, sender=None):
        return runner.run_once(
            root=self.root, day=entry["date"], period=entry["period"],
            source="test", now_utc=now or self.now_at(entry),
            config=self.config, schedule=self.schedule,
            sender=sender or self.sender, messages=self.messages,
        )

    # ---- 课表数据 ----
    def test_week_expressions(self):
        self.assertEqual(model.parse_weeks("3-13周,16-18周(混合)"),
                         list(range(3, 14)) + [16, 17, 18])
        self.assertEqual(model.parse_weeks("3周,6周,9周,12周,17周(实践)"),
                         [3, 6, 9, 12, 17])
        self.assertEqual(model.parse_weeks("4-7周,12-13周,16周(讲课)"),
                         [4, 5, 6, 7, 12, 13, 16])
        self.assertEqual(model.parse_weeks("18周(实训)"), [18])
        with self.assertRaises(ValueError):
            model.parse_weeks("3-13周,看不清")

    def test_week_index(self):
        self.assertEqual(model.week_index("2026-11-16", "2026-09-07"), 11)
        self.assertEqual(model.week_index("2026-09-07", "2026-09-07"), 1)

    def test_schedule_has_real_courses(self):
        data = self.schedule
        keys = [e["key"] for e in data["entries"]]
        self.assertEqual(len(keys), len(set(keys)), "唯一键重复")
        self.assertTrue(data["entries"])
        for e in data["entries"]:
            self.assertTrue(e["courses"], "%s 是空壳提醒" % e["key"])
            for c in e["courses"]:
                self.assertTrue(c.get("name"), "%s 缺课程名" % e["key"])
                self.assertTrue(c.get("room"), "%s 缺教室" % e["key"])
            self.assertTrue(1 <= e["week"] <= 18)

    def test_known_days_and_gaps(self):
        by_date = {}
        for e in self.schedule["entries"]:
            by_date.setdefault(e["date"], set()).add(e["period"])
        self.assertEqual(by_date[DAY], {"P1", "P3", "P4"})
        self.assertIn("P2", by_date["2026-11-20"], "周五第二大节的工程数学不能漏")
        self.assertNotIn("2026-12-07", by_date, "第 14 周应停课")
        self.assertNotIn("2026-12-14", by_date, "第 15 周应停课")
        self.assertNotIn("2026-11-21", by_date, "周六无课")

    def test_key_is_two_part(self):
        self.assertEqual(model.make_key(DAY, "P1"), "2026-11-16-P1")
        with self.assertRaises(ValueError):
            model.make_key(DAY, "P9")

    # ---- 消息 ----
    def test_message_contains_whole_day(self):
        entries = self.entries_of()
        title, body = notifier.render(entries[0], entries, self.messages)
        self.assertIn("08:40", title)
        self.assertIn("机械制图", body)
        self.assertIn("天工楼361", body)
        self.assertIn("工程数学11", body, "一条消息里必须给出今天其余的课")
        self.assertIn("思想道德与法治36", body)
        self.assertLessEqual(len(title), 32)

    def test_late_is_disclosed(self):
        entries = self.entries_of()
        _, body = notifier.render(entries[0], entries, self.messages, late_by_min=7)
        self.assertIn("晚到", body)
        self.assertIn("7 分钟", body)

    def test_preview_does_not_write_log(self):
        out = runner.preview(DAY, config=self.config, schedule=self.schedule,
                             messages=self.messages, sender=self.sender)
        self.assertEqual(out["courses"], 3)
        self.assertEqual(out["result"]["status"], "ok")
        self.assertFalse(ledger.log_path(self.root, DAY).exists(),
                         "手工预览不能冒充自动运行日志")
        self.assertIn("不计入自动运行日志", self.calls[0][1])

    # ---- 单轮行为 ----
    def test_all_periods_push_once(self):
        entries = self.entries_of()
        for e in entries:
            self.assertEqual(self.call(e)["result"], "ok")
        self.assertEqual(len(self.calls), len(entries))
        rows = ledger.read_records(self.root, DAY)
        self.assertEqual(len({r["key"] for r in rows}), len(entries))

    def test_no_class_day_is_silent(self):
        rec = runner.run_once(
            root=self.root, day="2026-11-21", period="P1", source="cron",
            now_utc=model.utc_datetime("2026-11-21", "08:20"),
            config=self.config, schedule=self.schedule,
            sender=self.sender, messages=self.messages)
        self.assertEqual(rec["action"], "no_schedule")
        self.assertEqual(len(self.calls), 0)

    def test_week_without_this_course_is_silent(self):
        # 第 14 周（12-07 周一）全校停课
        rec = runner.run_once(
            root=self.root, day="2026-12-07", period="P1", source="cron",
            now_utc=model.utc_datetime("2026-12-07", "08:20"),
            config=self.config, schedule=self.schedule,
            sender=self.sender, messages=self.messages)
        self.assertEqual(rec["action"], "no_schedule")
        self.assertEqual(len(self.calls), 0)

    def test_duplicate_not_pushed_twice(self):
        e = self.entries_of()[0]
        self.assertEqual(self.call(e)["action"], "send")
        self.assertEqual(self.call(e)["action"], "duplicate")
        self.assertEqual(len(self.calls), 1)

    def test_late_and_after_class(self):
        entries = self.entries_of()
        # 08:20 的提醒点：迟到 17 分钟（08:37）已超 15 分钟容差，但还没到 08:40 上课
        late = self.call(entries[0], now=self.now_at(entries[0], 17 * 60))
        self.assertEqual(late["action"], "skipped_late")
        # 换一节测上课后硬截止，避免被上一轮的去重状态判成 duplicate
        after = self.call(entries[1], now=model.utc_datetime(DAY, "13:31"))
        self.assertEqual(after["action"], "skipped_after_class")
        self.assertEqual(len(self.calls), 0)

    def test_early_skipped(self):
        e = self.entries_of()[0]
        rec = self.call(e, now=self.now_at(e, -10 * 60))
        self.assertEqual(rec["action"], "skipped_early")

    def test_failure_recorded_and_scrubbed(self):
        def bad_sender(title, content):
            return {"status": "failed", "http_status": 500, "duration_ms": 30,
                    "error": "POST https://sctapi.ftqq.com/SCT_SECRETKEY123.send?key=SECRET123 failed",
                    "channel": "serverchan_turbo"}

        rec = self.call(self.entries_of()[0], sender=bad_sender)
        self.assertEqual(rec["result"], "error")
        text = ledger.log_path(self.root, DAY).read_text(encoding="utf-8")
        self.assertNotIn("SECRET123", text)
        self.assertIn("[url]", text)

    def test_hash_chain_and_verify(self):
        entries = self.entries_of()
        for e in entries:
            self.call(e)
        rows = ledger.read_records(self.root, DAY)
        prev = "genesis"
        for r in rows:
            self.assertEqual(r["prev_hash"], prev)
            self.assertEqual(r["hash"], ledger.chain_hash(prev, r))
            prev = r["hash"]
        ledger.rollup(self.root, DAY, expected=len(entries))
        ref = model.utc_datetime(DAY, "16:00").astimezone(model.CST)
        report = verify.verify_day(self.root, DAY, self.schedule, now=ref)
        self.assertTrue(report["all_ok"], report)

    # ---- 通道 / 产物 ----
    def test_missing_key_fails_without_network(self):
        env = {k: v for k, v in os.environ.items() if k != "PREBELL_SENDKEY"}
        with mock.patch.dict(os.environ, env, clear=True):
            res = channels.send_serverchan("标题", "正文", self.config)
        self.assertEqual(res["status"], "failed")
        self.assertIn("missing credential", res["error"])

    def test_secrets_scrubbed(self):
        # 只用运行时拼出来的虚构串做样本：绝不把真实 SendKey 写进仓库文件，
        # 也不在源码里留下形似密钥的完整字符串（转公开前全仓扫描要零命中）。
        # 脱敏规则是 sctp?[A-Za-z0-9_-]{8,}，拆开拼仍能触发同一条规则。
        for token in ("SCT" + "000000Fake" + "TestKeyForScrubCheck",
                      "SCT" + "_FAKE_KEY_123"):
            clean = model.scrub_text(token)
            self.assertNotIn(token, clean, "%s 没被抹掉" % token)
            self.assertIn("[sendkey]", clean)
        self.assertIn("[url]", model.scrub_text("https://example.com/a?key=abc"))

    def test_ics_and_html(self):
        ics = planner.render_ics(self.schedule)
        self.assertIn("BEGIN:VCALENDAR", ics)
        self.assertIn("BEGIN:VALARM", ics)
        self.assertIn("TRIGGER:-PT20M", ics)
        self.assertIn("机械制图", ics)
        self.assertEqual(ics.count("BEGIN:VEVENT"), self.schedule["total_entries"])
        html = planner.render_html(self.schedule)
        self.assertIn("const DATA =", html)
        self.assertIn("下载课表 .ics", html)
        self.assertIn("<script>", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
