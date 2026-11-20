"""TASK-0075 SM-2 简化版复习调度单测（srs.schedule 纯函数契约，OP-05 测试批 1）。

运行：cd tools/french-learner/backend && python -m unittest tests.test_srs -v
合并回归：python -X utf8 -m unittest discover -s tests -t . -p "test_*.py" -v
零新增依赖（unittest 标准库）。

覆盖：
- rating 各档分支：>=3 记得（rep+1，interval 阶梯 1→6→round(prev*EF)）、<3 忘记（rep 清零、interval=1）
- EF 更新公式：q=5 增 / q=4 不变 / q=3,2,1 递减；1.3 下限钳制与负向累计
- next_due：ISO8601 UTC+Z 格式、now+interval 偏移
- 契约固化：schedule 为纯函数不改入参 state；缺 state key / rating 越界的当前行为
  （产品不做入参兜底，docstring 声明由 API 层校验——测试固化现状，若后续加兜底需连同用例一起评审）。
"""
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BACKEND = str(Path(__file__).resolve().parents[1])
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import srs  # noqa: E402

DUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def state(rep=0, ef=2.5, interval=0):
    """构造 SM-2 状态（无参即初始态 (0, 2.5, 0)）。"""
    return {"repetitions": rep, "ease_factor": ef, "interval_days": interval}


class TestRememberBranch(unittest.TestCase):
    """rating >= 3：记得，repetitions 累加、interval 走阶梯。"""

    def test_first_review_interval_1(self):
        new_state, _, interval = srs.schedule(4, state())
        self.assertEqual(interval, 1)
        self.assertEqual(new_state["repetitions"], 1)

    def test_second_review_interval_6(self):
        _, _, interval = srs.schedule(4, state(rep=1, interval=1))
        self.assertEqual(interval, 6)

    def test_third_interval_prev_times_ef(self):
        _, _, interval = srs.schedule(4, state(rep=2, ef=2.5, interval=6))
        self.assertEqual(interval, 15)  # round(6 * 2.5)

    def test_ladder_rating4_sequence(self):
        # q=4 时 EF 增量恰为 0，阶梯纯粹由 2.5 倍增驱动。
        # 注意 15*2.5=37.5，CPython round 半数到偶 → 38（固化当前行为）。
        st = state()
        intervals = []
        for _ in range(5):
            st, _, interval = srs.schedule(4, st)
            intervals.append(interval)
        self.assertEqual(intervals, [1, 6, 15, 38, 95])
        self.assertEqual(st["repetitions"], 5)


class TestForgetBranch(unittest.TestCase):
    """rating < 3：忘记，repetitions 清零、interval 归 1。"""

    def test_rating2_resets_repetitions(self):
        new_state, _, interval = srs.schedule(2, state(rep=3, ef=2.5, interval=15))
        self.assertEqual(new_state["repetitions"], 0)
        self.assertEqual(interval, 1)

    def test_rating1_resets_repetitions(self):
        new_state, _, interval = srs.schedule(1, state(rep=5, ef=2.0, interval=30))
        self.assertEqual(new_state["repetitions"], 0)
        self.assertEqual(interval, 1)

    def test_lapse_then_relearn_restarts_ladder(self):
        st, _, _ = srs.schedule(1, state(rep=4, ef=2.0, interval=30))
        st, _, interval = srs.schedule(4, st)
        self.assertEqual(st["repetitions"], 1)  # 从头重新爬梯
        self.assertEqual(interval, 1)

    def test_forget_interval_is_1_even_after_long_run(self):
        _, _, interval = srs.schedule(2, state(rep=6, ef=2.5, interval=95))
        self.assertEqual(interval, 1)


class TestEaseFactor(unittest.TestCase):
    """EF 更新：EF += 0.1 - (5-q)*(0.08 + (5-q)*0.02)，下限钳制 1.3。"""

    def test_rating4_ef_unchanged(self):
        st, _, _ = srs.schedule(4, state())
        self.assertAlmostEqual(st["ease_factor"], 2.5, places=9)

    def test_rating5_ef_increase(self):
        st, _, _ = srs.schedule(5, state())
        self.assertAlmostEqual(st["ease_factor"], 2.6, places=9)

    def test_rating3_ef_decrease(self):
        st, _, _ = srs.schedule(3, state())
        self.assertAlmostEqual(st["ease_factor"], 2.36, places=9)

    def test_rating2_ef_decrease(self):
        st, _, _ = srs.schedule(2, state())
        self.assertAlmostEqual(st["ease_factor"], 2.18, places=9)

    def test_rating1_ef_decrease(self):
        st, _, _ = srs.schedule(1, state())
        self.assertAlmostEqual(st["ease_factor"], 1.96, places=9)

    def test_cumulative_decay_rating3(self):
        # 连续"想起但勉强"（q=3）时 EF 每次降 0.14，负向累计。
        st = state()
        for expected in (2.36, 2.22, 2.08, 1.94, 1.80):
            st, _, _ = srs.schedule(3, st)
            self.assertAlmostEqual(st["ease_factor"], expected, places=6)

    def test_ef_clamped_at_floor_1_3(self):
        # 2.5 → 1.96 → 1.42 → 0.88（钳到 1.3），此后继续失败不再下探。
        st = state()
        for _ in range(5):
            st, _, _ = srs.schedule(1, st)
        self.assertEqual(st["ease_factor"], 1.3)

    def test_ef_floor_stable_under_more_failures(self):
        st = state(rep=3, ef=1.3, interval=10)
        for _ in range(3):
            st, _, _ = srs.schedule(1, st)
            self.assertEqual(st["ease_factor"], 1.3)


class TestNextDue(unittest.TestCase):
    """next_due 为 ISO8601 UTC+Z 字符串，等于 now + interval 天。"""

    def test_iso_z_format(self):
        _, due, _ = srs.schedule(4, state())
        self.assertRegex(due, DUE_RE)

    def test_offset_matches_interval(self):
        before = datetime.now(timezone.utc)
        _, due, interval = srs.schedule(4, state(rep=2, interval=6))
        after = datetime.now(timezone.utc)
        parsed = datetime.strptime(due, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        lower = before + timedelta(days=interval) - timedelta(seconds=10)
        upper = after + timedelta(days=interval) + timedelta(seconds=10)
        self.assertTrue(lower <= parsed <= upper)

    def test_forget_due_about_one_day(self):
        before = datetime.now(timezone.utc)
        _, due, interval = srs.schedule(1, state())
        parsed = datetime.strptime(due, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self.assertEqual(interval, 1)
        self.assertLess(abs((parsed - before).total_seconds() - 86400), 10)


class TestContract(unittest.TestCase):
    """纯函数性与异常输入的当前行为固化。"""

    def test_input_state_not_mutated(self):
        st = state(rep=3, ef=2.2, interval=10)
        snapshot = dict(st)
        srs.schedule(4, st)
        self.assertEqual(st, snapshot)

    def test_returns_tuple_and_state_keys(self):
        result = srs.schedule(4, state())
        self.assertIsInstance(result, tuple)
        new_state, due, interval = result
        self.assertEqual(set(new_state), {"repetitions", "ease_factor", "interval_days"})
        self.assertIsInstance(due, str)
        self.assertIsInstance(interval, int)

    def test_missing_state_key_raises_keyerror(self):
        # 产品现状：schedule 不做入参兜底（docstring 声明由 API 层校验），缺 key 直接 KeyError。
        with self.assertRaises(KeyError):
            srs.schedule(4, {"repetitions": 0})

    def test_rating0_treated_as_forget(self):
        # rating 范围校验在 API 层；0 进入忘记分支且 EF 大幅衰减（固化当前行为）。
        new_state, _, interval = srs.schedule(0, state())
        self.assertEqual(new_state["repetitions"], 0)
        self.assertEqual(interval, 1)
        self.assertAlmostEqual(new_state["ease_factor"], 1.7, places=9)

    def test_rating5_remember_branch(self):
        new_state, _, interval = srs.schedule(5, state())
        self.assertEqual(new_state["repetitions"], 1)
        self.assertEqual(interval, 1)


if __name__ == "__main__":
    unittest.main()
