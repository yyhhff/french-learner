"""TASK-0070 v3.0 gamify 单测：等级曲线纯函数 + award 封顶 + today_summary 聚合。

等级曲线不落库纯函数直测；award/summary 用临时内存库（db.get_conn 指向临时文件）
避免污染主库。主库数据零污染是硬要求。
"""
import os
import sqlite3
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gamify  # noqa: E402


class TestLevelCurve(unittest.TestCase):
    """等级曲线纯函数：阈值、边界、命名。"""

    def test_lv1_at_59_and_60(self):
        self.assertEqual(gamify.level_for_xp(0)["level"], 1)
        self.assertEqual(gamify.level_for_xp(59)["level"], 1)
        self.assertEqual(gamify.level_for_xp(60)["level"], 2)

    def test_thresholds_monotonic(self):
        self.assertEqual(gamify.xp_total_for_level(1), 0)
        self.assertEqual(gamify.xp_total_for_level(2), 60)
        self.assertEqual(gamify.xp_total_for_level(3), 180)
        self.assertEqual(gamify.xp_total_for_level(4), 360)
        self.assertLess(gamify.xp_total_for_level(1), gamify.xp_total_for_level(2))

    def test_negative_and_types(self):
        r = gamify.level_for_xp(-5)
        self.assertEqual(r["level"], 1)
        self.assertIsInstance(r["cur"], int)
        self.assertGreaterEqual(r["cur"], 0)

    def test_segment_progress_consistent(self):
        for xp in (0, 60, 179, 180, 359, 500):
            r = gamify.level_for_xp(xp)
            self.assertGreaterEqual(r["cur"], 0)
            self.assertLess(r["cur"], r["need"])
            self.assertEqual(r["name"], gamify.LEVEL_NAMES.get(r["level"], r["name"]))


class TestAwardCaps(unittest.TestCase):
    """award 日封顶与明细落库：用独立临时库，主库零污染。"""

    def setUp(self):
        self.tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "yaya_test_gamify.db")
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

        def _fake_conn():
            c = sqlite3.connect(self.tmp)
            c.row_factory = sqlite3.Row
            return c

        self._conn_patch = mock.patch.object(gamify.db, "get_conn", side_effect=_fake_conn)
        self.m = self._conn_patch.start()
        conn = sqlite3.connect(self.tmp)
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, xp INTEGER DEFAULT 0,
                streak_days INTEGER DEFAULT 0, last_active_date TEXT,
                cefr_level TEXT DEFAULT 'A2');
            INSERT INTO users (id, xp, streak_days) VALUES (1, 0, 0);
            CREATE TABLE xp_events (id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, day TEXT, source TEXT, amount INTEGER,
                detail TEXT, created_at TEXT);
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self._conn_patch.stop()
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def test_award_inserts_and_updates_xp(self):
        got = gamify.award("read", 15, detail="gen_a1_001", user_id=1)
        self.assertEqual(got, 15)
        conn = sqlite3.connect(self.tmp)
        total = conn.execute("SELECT xp FROM users WHERE id=1").fetchone()[0]
        n = conn.execute("SELECT COUNT(*) FROM xp_events").fetchone()[0]
        conn.close()
        self.assertEqual(total, 15)
        self.assertEqual(n, 1)

    def test_chat_daily_cap_30(self):
        for _ in range(12):  # 12 次 × 3xp = 36 > 30
            gamify.award("chat", 3, user_id=1)
        conn = sqlite3.connect(self.tmp)
        s = conn.execute("SELECT SUM(amount) FROM xp_events WHERE source='chat'").fetchone()[0]
        conn.close()
        self.assertEqual(s, 30)

    def test_shadow_daily_cap_20(self):
        for _ in range(6):  # 6 次 × 5 = 30 > 20
            gamify.award("shadow", 5, user_id=1)
        conn = sqlite3.connect(self.tmp)
        s = conn.execute("SELECT SUM(amount) FROM xp_events WHERE source='shadow'").fetchone()[0]
        conn.close()
        self.assertEqual(s, 20)

    def test_zero_or_negative_noop(self):
        self.assertEqual(gamify.award("review", 0, user_id=1), 0)
        self.assertEqual(gamify.award("review", -3, user_id=1), 0)


class TestTodaySummary(unittest.TestCase):
    """today_summary 聚合：任务口径 + 永不 500。"""

    def setUp(self):
        self.tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "yaya_test_gamify2.db")
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

        def _fake_conn():
            c = sqlite3.connect(self.tmp)
            c.row_factory = sqlite3.Row
            return c

        self._patch = mock.patch.object(gamify.db, "get_conn", side_effect=_fake_conn)
        self.m = self._patch.start()
        conn = sqlite3.connect(self.tmp)
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, xp INTEGER DEFAULT 0,
                streak_days INTEGER DEFAULT 0, last_active_date TEXT,
                cefr_level TEXT DEFAULT 'A2');
            INSERT INTO users (id, cefr_level) VALUES (1, 'A1');
            CREATE TABLE reading_logs (id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, text_id TEXT, cefr_level TEXT, title TEXT,
                created_at TEXT, UNIQUE(user_id, text_id));
            CREATE TABLE review_logs (id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, card_id INTEGER, rating INTEGER,
                next_due TEXT, last_reviewed_at TEXT);
            CREATE TABLE dialogue_turns (id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, scene_id TEXT, role TEXT, fr TEXT, cn TEXT,
                recast_of TEXT, explanation TEXT, is_correction INTEGER,
                created_at TEXT);
            CREATE TABLE xp_events (id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, day TEXT, source TEXT, amount INTEGER,
                detail TEXT, created_at TEXT);
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self._patch.stop()
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def test_a1_chat_target_is_3(self):
        r = gamify.today_summary(user_id=1)
        chat = next(t for t in r["tasks"] if t["key"] == "chat")
        self.assertEqual(chat["target"], 3)

    def test_no_due_means_review_done(self):
        r = gamify.today_summary(user_id=1)
        review = next(t for t in r["tasks"] if t["key"] == "review")
        self.assertTrue(review["done"])
        self.assertEqual(review["target"], 0)

    def test_never_raises_on_missing_tables(self):
        conn = sqlite3.connect(self.tmp)
        conn.execute("DROP TABLE reading_logs")
        conn.commit()
        conn.close()
        r = gamify.today_summary(user_id=1)  # 不应抛异常
        self.assertIn("tasks", r)
        self.assertIn("xp", r)


if __name__ == "__main__":
    unittest.main()
