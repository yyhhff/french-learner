"""TASK-0075 阶段0 CEFR 定级单测（assessment：题库加载/判分/定级/中文解读，OP-05 测试批 1）。

运行：cd tools/french-learner/backend && python -m unittest tests.test_assessment -v
合并回归：python -X utf8 -m unittest discover -s tests -t . -p "test_*.py" -v

边界说明：
- data/input/assessment_questions.json 为入 git 的稳定 v2 题库（24 题四档各 6），
  测试只读、绝不修改；对真实题库的结构断言固定为 24 题口径。
- 加载降级类用例通过 mock.patch.object 替换 INPUT_FILE 与 _QUESTIONS_CACHE，
  合成 JSON 写入系统临时目录（tempfile 自动清理），不在仓库内落盘。
- 判分容错类用例固化当前行为（grade 对未知 id / 缺 answer_idx 直接 KeyError，
  入参校验在 API 层）；若后续产品加兜底，需连同用例一起评审。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_BACKEND = str(Path(__file__).resolve().parents[1])
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import assessment  # noqa: E402

VALID_Q = {
    "id": "ut_a1_001", "level": "A1", "skill": "词汇",
    "question": "Bonjour 是什么意思？", "options": ["你好", "再见", "谢谢", "晚安"],
    "answer_idx": 0, "explanation_zh": "Bonjour 即你好。",
}


def make_question(qid, level, skill="词汇", answer_idx=0):
    """构造一道通过 §2.2 校验的合成题。"""
    return {
        "id": qid, "level": level, "skill": skill,
        "question": f"合成题 {qid}", "options": ["甲", "乙", "丙", "丁"],
        "answer_idx": answer_idx, "explanation_zh": "解析文本",
    }


def make_bank(per_level=2):
    """合成题库：四档各 per_level 题（判分/定级边界用，不依赖真实题库内容）。"""
    bank = []
    for level in assessment.LEVELS:
        for k in range(per_level):
            bank.append(make_question(f"ut_{level.lower()}_{k}", level, answer_idx=k % 4))
    return bank


def flag(skill, correct):
    """构造 weak_skill 的输入明细（weak_skill 只读 skill / correct）。"""
    return {"id": "x", "skill": skill, "correct": correct}


class AssessmentTestBase(unittest.TestCase):
    """公共夹具：临时 JSON 文件 + INPUT_FILE/_QUESTIONS_CACHE 替换。"""

    def temp_path(self, name="bank.json", text=None):
        tmpdir = tempfile.TemporaryDirectory(prefix="yaya_asmt_ut_")
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / name
        if text is not None:
            path.write_text(text, encoding="utf-8")
        return path

    def patch_input(self, path):
        for attr, value in (("INPUT_FILE", path), ("_QUESTIONS_CACHE", None)):
            patcher = mock.patch.object(assessment, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def load_with(self, text):
        self.patch_input(self.temp_path(text=text))
        return assessment.load_questions()


class TestLoadQuestions(AssessmentTestBase):
    """题库加载：真实题库结构、缓存幂等、异常降级。"""

    def test_real_bank_24_four_levels(self):
        qs = assessment.load_questions()
        self.assertEqual(len(qs), 24)
        per_level = {lv: sum(1 for q in qs if q["level"] == lv) for lv in assessment.LEVELS}
        self.assertEqual(per_level, {"A1": 6, "A2": 6, "B1": 6, "B2": 6})

    def test_real_bank_fields_skills_ids(self):
        qs = assessment.load_questions()
        ids = [q["id"] for q in qs]
        self.assertEqual(len(set(ids)), len(ids))
        per_level_skill = {}
        for q in qs:
            self.assertEqual(
                set(q), {"id", "level", "skill", "question", "options", "answer_idx", "explanation_zh"})
            self.assertIsInstance(q["answer_idx"], int)  # bool 是 int 子类，真题库不应出现
            self.assertFalse(isinstance(q["answer_idx"], bool))
            self.assertTrue(0 <= q["answer_idx"] <= 3)
            self.assertEqual(len(q["options"]), 4)
            per_level_skill[(q["level"], q["skill"])] = per_level_skill.get((q["level"], q["skill"]), 0) + 1
        self.assertEqual(len(per_level_skill), 12)  # 4 档 × 3 技能
        self.assertTrue(all(v == 2 for v in per_level_skill.values()))  # 每格各 2 题

    def test_load_idempotent_cache(self):
        self.assertIs(assessment.load_questions(), assessment.load_questions())

    def test_missing_file_degrades_empty(self):
        self.patch_input(self.temp_path(text=None))
        self.assertEqual(assessment.load_questions(), [])

    def test_corrupt_json_degrades_empty(self):
        self.assertEqual(self.load_with('{"questions": ['), [])

    def test_invalid_questions_field_degrades_empty(self):
        self.assertEqual(self.load_with(json.dumps({"questions": "oops"})), [])
        self.assertEqual(self.load_with(json.dumps({"meta": 1})), [])

    def test_invalid_and_duplicate_skipped(self):
        q_a = make_question("ut_a", "A1")
        q_b = make_question("ut_b", "A2", skill="语法", answer_idx=2)
        bad_no_explanation = {"id": "ut_bad", "level": "B1", "skill": "理解",
                              "question": "缺解析", "options": ["甲", "乙", "丙", "丁"],
                              "answer_idx": 1}
        payload = json.dumps({"questions": [q_a, q_b, bad_no_explanation, "junk", q_a]})
        loaded = self.load_with(payload)
        self.assertEqual([q["id"] for q in loaded], ["ut_a", "ut_b"])  # 非法/重复/非 dict 均跳过


class TestValidQuestion(unittest.TestCase):
    """§2.2 单题逐字段校验。"""

    def test_valid_question_accepted(self):
        self.assertTrue(assessment._valid_question(VALID_Q))

    def test_bool_answer_idx_rejected(self):
        # bool 是 int 子类，必须显式拒绝（True 会被当成 1）。
        self.assertFalse(assessment._valid_question({**VALID_Q, "answer_idx": True}))

    def test_answer_idx_out_of_range_rejected(self):
        for bad in (-1, 4, 0.5, None):
            with self.subTest(answer_idx=bad):
                self.assertFalse(assessment._valid_question({**VALID_Q, "answer_idx": bad}))

    def test_options_problems_rejected(self):
        cases = {
            "三选项": {**VALID_Q, "options": ["甲", "乙", "丙"]},
            "去空格后重复": {**VALID_Q, "options": ["你好", "再见", " 你好 ", "晚安"]},
            "空选项": {**VALID_Q, "options": ["你好", "", "谢谢", "晚安"]},
            "非字符串选项": {**VALID_Q, "options": ["你好", 2, "谢谢", "晚安"]},
        }
        for name, case in cases.items():
            with self.subTest(case=name):
                self.assertFalse(assessment._valid_question(case))

    def test_blank_or_illegal_fields_rejected(self):
        cases = {
            "空白 id": {**VALID_Q, "id": "  "},
            "空题干": {**VALID_Q, "question": ""},
            "非法档位": {**VALID_Q, "level": "C1"},
            "非法技能": {**VALID_Q, "skill": "听力"},
            "缺解析": {k: v for k, v in VALID_Q.items() if k != "explanation_zh"},
        }
        for name, case in cases.items():
            with self.subTest(case=name):
                self.assertFalse(assessment._valid_question(case))

    def test_non_dict_rejected(self):
        self.assertFalse(assessment._valid_question("not a dict"))
        self.assertFalse(assessment._valid_question(None))
        self.assertFalse(assessment._valid_question(["id"]))


class TestPublicQuestions(unittest.TestCase):
    """PUBLIC_FIELDS 白名单投影：绝不下发 answer_idx / explanation_zh。"""

    def test_whitelist_exact_fields_no_leak(self):
        proj = assessment.public_questions(assessment.load_questions())
        for p in proj:
            self.assertEqual(set(p), set(assessment.PUBLIC_FIELDS))
        dumped = json.dumps(proj, ensure_ascii=False)
        self.assertNotIn("answer_idx", dumped)
        self.assertNotIn("explanation_zh", dumped)

    def test_projection_preserves_order_and_values(self):
        qs = assessment.load_questions()
        proj = assessment.public_questions(qs)
        self.assertEqual([p["id"] for p in proj], [q["id"] for q in qs])
        self.assertEqual(proj[0]["options"], qs[0]["options"])
        self.assertEqual(proj[0]["level"], qs[0]["level"])


class TestLevelFromCounts(unittest.TestCase):
    """v1.2 §4.3 分组下限定级：高档需本级与其下各级均 >=4，保底 A1。"""

    def test_b2_gate(self):
        for counts in ((4, 4, 4, 4), (5, 5, 5, 5), (6, 6, 6, 6)):
            with self.subTest(counts=counts):
                self.assertEqual(assessment.level_from_counts(*counts), "B2")

    def test_b1_gate(self):
        # B2 有短板即回落 B1；B1 只看 A1/A2/B1 三档。
        for counts in ((4, 4, 4, 3), (4, 4, 4, 0), (6, 6, 6, 2)):
            with self.subTest(counts=counts):
                self.assertEqual(assessment.level_from_counts(*counts), "B1")

    def test_a2_gate(self):
        # A2 只看 A1/A2 两档，高档满分也救不了低档短板。
        for counts in ((4, 4, 0, 0), (6, 4, 0, 6), (4, 4, 3, 0)):
            with self.subTest(counts=counts):
                self.assertEqual(assessment.level_from_counts(*counts), "A2")

    def test_a1_floor_and_no_skip(self):
        # 保底 A1：全档未达标 / B2 全对但 A1 未达标（防零基础蒙题跳级）。
        for counts in ((3, 3, 3, 3), (0, 0, 0, 6), (6, 0, 0, 0), (0, 4, 4, 4), (4, 3, 4, 4), (0, 0, 0, 0)):
            with self.subTest(counts=counts):
                self.assertEqual(assessment.level_from_counts(*counts), "A1")


class TestGrade(unittest.TestCase):
    """§4.2 判分：按 id 匹配、加权得分、防跳级定级、逐题明细。"""

    def _correct(self, q):
        return {"id": q["id"], "answer_idx": q["answer_idx"]}

    def _wrong(self, q):
        return {"id": q["id"], "answer_idx": (q["answer_idx"] + 1) % 4}

    def test_all_correct_real_bank(self):
        qs = assessment.load_questions()
        result = assessment.grade([self._correct(q) for q in qs], qs)
        self.assertEqual(result["score"], 24)
        self.assertEqual(result["weighted_score"], 36)  # 6*(0+1+2+3)
        self.assertEqual(result["level"], "B2")
        self.assertEqual(result["rate"], 1.0)
        self.assertEqual(result["weak_skill"], "词汇")  # 全满并列时取首个技能
        self.assertTrue(all(f["correct"] for f in result["correct_flags"]))

    def test_all_wrong_real_bank(self):
        qs = assessment.load_questions()
        result = assessment.grade([self._wrong(q) for q in qs], qs)
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["weighted_score"], 0)
        self.assertEqual(result["level"], "A1")  # 保底
        self.assertEqual(result["rate"], 0.0)
        self.assertEqual(result["weak_skill"], "词汇")  # 全零并列时取首个技能

    def test_mixed_per_level_gate_b2(self):
        # 每档恰好答对 4 题：分组下限恰好达标 → B2；加权 4*(0+1+2+3)=24。
        qs = assessment.load_questions()
        answers = []
        for level in assessment.LEVELS:
            for i, q in enumerate([x for x in qs if x["level"] == level]):
                answers.append(self._correct(q) if i < 4 else self._wrong(q))
        result = assessment.grade(answers, qs)
        self.assertEqual(result["score"], 16)
        self.assertEqual(result["weighted_score"], 24)
        self.assertEqual(result["level"], "B2")
        self.assertEqual(result["rate"], 0.6667)

    def test_no_skip_level_b2_only_synthetic(self):
        # 防跳级：只有 B2 全对（其余全错）→ 仍落 A1；加权总分不为定级依据。
        bank = make_bank(per_level=2)
        b2_ids = {q["id"] for q in bank if q["level"] == "B2"}
        answers = [self._correct(q) if q["id"] in b2_ids else self._wrong(q) for q in bank]
        result = assessment.grade(answers, bank)
        self.assertEqual(result["level"], "A1")
        self.assertEqual(result["score"], 2)
        self.assertEqual(result["weighted_score"], 6)  # 2*3
        self.assertEqual(result["rate"], 0.25)

    def test_weighted_score_small_bank(self):
        # 权重算术：2 题/档全对 → 加权 2*(0+1+2+3)=12；
        # 每档仅 2 题达不到 4/6 门槛，定级保底 A1（判定级不用加权总分）。
        bank = make_bank(per_level=2)
        result = assessment.grade([self._correct(q) for q in bank], bank)
        self.assertEqual(result["weighted_score"], 12)
        self.assertEqual(result["level"], "A1")
        self.assertEqual(result["score"], 8)

    def test_all_correct_six_per_level_synthetic_b2(self):
        # 6 题/档全对 → counts (6,6,6,6) 过全部门槛 → B2，加权满分 36。
        bank = make_bank(per_level=6)
        result = assessment.grade([self._correct(q) for q in bank], bank)
        self.assertEqual(result["level"], "B2")
        self.assertEqual(result["weighted_score"], 36)
        self.assertEqual(result["score"], 24)

    def test_match_by_id_not_order(self):
        # 判分按 id 匹配、不信提交顺序：乱序提交结果一致。
        bank = make_bank(per_level=2)
        answers = [self._correct(q) for q in bank]
        in_order = assessment.grade(answers, bank)
        shuffled = assessment.grade(list(reversed(answers)), bank)
        for key in ("score", "weighted_score", "level", "rate", "weak_skill"):
            self.assertEqual(in_order[key], shuffled[key], key)
        self.assertEqual(
            sorted(in_order["correct_flags"], key=lambda f: f["id"]),
            sorted(shuffled["correct_flags"], key=lambda f: f["id"]),
        )

    def test_answer_idx_out_of_range_counted_wrong(self):
        # 越界/负数 answer_idx 与正确答案必不相等：容错计为答错，不抛异常。
        bank = make_bank(per_level=2)
        for bad in (9, -1):
            with self.subTest(answer_idx=bad):
                result = assessment.grade([{"id": bank[0]["id"], "answer_idx": bad}], bank)
                self.assertEqual(result["score"], 0)
                self.assertFalse(result["correct_flags"][0]["correct"])

    def test_unknown_answer_id_raises_keyerror(self):
        # 产品现状：未知 id 直接 KeyError（题库换版后前端提交陈旧 id 会 500，
        # 依赖 API 层校验兜底）；此处固化当前行为。
        bank = make_bank(per_level=2)
        with self.assertRaises(KeyError):
            assessment.grade([{"id": "ghost", "answer_idx": 0}], bank)

    def test_missing_answer_idx_raises_keyerror(self):
        # 产品现状：缺 answer_idx 直接 KeyError（入参校验在 API 层）。
        bank = make_bank(per_level=2)
        with self.assertRaises(KeyError):
            assessment.grade([{"id": bank[0]["id"]}], bank)

    def test_flags_detail_fields(self):
        bank = make_bank(per_level=2)
        result = assessment.grade([self._correct(bank[0])], bank)
        self.assertEqual(len(result["correct_flags"]), 1)
        f = result["correct_flags"][0]
        self.assertEqual(set(f), {"id", "level", "skill", "answer_idx", "correct"})
        self.assertEqual(f["level"], bank[0]["level"])
        self.assertEqual(f["skill"], bank[0]["skill"])
        self.assertTrue(f["correct"])

    def test_empty_answers_contract(self):
        bank = make_bank(per_level=2)
        result = assessment.grade([], bank)
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["rate"], 0.0)
        self.assertEqual(result["level"], "A1")
        self.assertEqual(result["weak_skill"], "词汇")
        self.assertEqual(result["correct_flags"], [])


class TestWeakSkill(unittest.TestCase):
    """§4.2 薄弱维度：按 skill 正确率取最低，并列按 词汇 < 语法 < 理解。"""

    def test_weakest_by_accuracy(self):
        flags = [flag("词汇", True), flag("词汇", True),
                 flag("语法", True), flag("语法", False),
                 flag("理解", False), flag("理解", False)]
        self.assertEqual(assessment.weak_skill(flags), "理解")

    def test_tie_break_prefers_earlier_skill(self):
        # 语法与理解同为 0%，并列时取顺序更前的"语法"。
        flags = [flag("词汇", True), flag("语法", False), flag("理解", False)]
        self.assertEqual(assessment.weak_skill(flags), "语法")

    def test_empty_flags_returns_vocab(self):
        self.assertEqual(assessment.weak_skill([]), "词汇")

    def test_unanswered_skill_counts_as_full(self):
        # 未出现过的技能按 100% 正确率计，不会被选为薄弱项。
        flags = [flag("词汇", False), flag("词汇", False)]
        self.assertEqual(assessment.weak_skill(flags), "词汇")


class TestInterpretation(unittest.TestCase):
    """§5 中文解读：固定前缀 + 等级文案 + 薄弱维度提示，逐字拼接。"""

    def test_exact_string_a2(self):
        expected = ("本次定级共 15 题，答对 10 题，正确率 67%。"
                    + assessment.INTERPRETATION_BY_LEVEL["A2"]
                    + "语法是你接下来可以多花点时间的地方。")
        self.assertEqual(
            assessment.interpretation_zh("A2", "语法", 10, 15, 0.6667), expected)

    def test_prefix_and_weak_hint_b1(self):
        out = assessment.interpretation_zh("B1", "理解", 7, 12, 0.5833)
        self.assertTrue(out.startswith("本次定级共 12 题，答对 7 题，正确率 58%。"))
        self.assertTrue(out.endswith("理解是你接下来可以多花点时间的地方。"))

    def test_all_level_texts_embedded(self):
        for lv in assessment.LEVELS:
            with self.subTest(level=lv):
                out = assessment.interpretation_zh(lv, "词汇", 1, 1, 1.0)
                self.assertIn(assessment.INTERPRETATION_BY_LEVEL[lv], out)
                self.assertIn("词汇是你接下来可以多花点时间的地方。", out)

    def test_zero_score_zero_pct(self):
        out = assessment.interpretation_zh("A1", "语法", 0, 24, 0.0)
        self.assertTrue(out.startswith("本次定级共 24 题，答对 0 题，正确率 0%。"))


if __name__ == "__main__":
    unittest.main()
