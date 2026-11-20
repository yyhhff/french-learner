"""TASK-0078 v3.3 语法微卡引擎单测（加载 / 扫描 / 标签 / 画像 / 推卡 / 端点）。

运行（单文件）：cd tools/french-learner/backend && python -m unittest tests.test_grammar -v
合并回归：python -X utf8 -m unittest discover -s tests -t . -p "test_*.py" -v

边界说明（沿 test_ai.py 惯例）：
- 零网络、零 GLM；db 层一律 mock，绝不读写真实 SQLite（backend/data/yaya.db）。
- data/input/grammar_cards.json 为入 git 的稳定 v3.3 卡库（50 卡），测试只读；
  另断言 JS 兼容红线：patterns 禁用 \\b 与后行断言（前端语法同源复扫）。
- 端点用例直接 await 路由协程（工程无 httpx，不引入 TestClient 依赖）。
"""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_BACKEND = str(Path(__file__).resolve().parents[1])
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import grammar  # noqa: E402
from routers import grammar as grammar_router  # noqa: E402


def _body(resp):
    """ok() JSONResponse → data 字段。"""
    return json.loads(resp.body)["data"]


class FakeResult:
    """chat 挂接用最小 result 桩（只要 recast_of / error_tag / explanation）。"""

    def __init__(self, recast_of=None, error_tag=None):
        self.ai_text = "Ah, je vois !"
        self.recast_of = recast_of
        self.explanation = "讲解"
        self.error_tag = error_tag


# ---------------------------------------------------------------- 卡库 schema

class TestCardsSchema(unittest.TestCase):
    """真实卡库的结构与红线断言（只读，不改文件）。"""

    @classmethod
    def setUpClass(cls):
        cls.cards = grammar.load_cards(force=True)

    def test_count_at_least_40(self):
        self.assertGreaterEqual(len(self.cards), 40, "总纲 v3.3 要求 40+ 微卡")

    def test_schema_all_valid(self):
        self.assertEqual(grammar.validate_cards(self.cards), [])

    def test_ids_unique(self):
        ids = [c["id"] for c in self.cards]
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_ten_tags_present(self):
        tags = {c["tag"] for c in self.cards}
        self.assertEqual(tags, set(grammar.ERROR_TAGS), "10 类错误标签每类都要有卡")

    def test_all_four_levels_present(self):
        levels = {c["level"] for c in self.cards}
        self.assertEqual(levels, set(grammar.LEVELS), "A1..B2 每级都要有卡")

    def test_patterns_js_compatible(self):
        # 前端 grammar.js 用同一算法复扫：禁 \b（JS 对重音字母失效）与后行断言
        for c in self.cards:
            for p in c["patterns"]:
                self.assertNotIn("\\b", p, f"{c['id']} pattern 用了 \\b：{p}")
                self.assertNotIn("(?<", p, f"{c['id']} pattern 用了后行断言：{p}")
                self.assertNotIn("(?=", p, f"{c['id']} pattern 用了前行断言：{p}")

    def test_file_unreadable_degrades_empty(self):
        with mock.patch.object(grammar, "INPUT_FILE", Path("Z:/不存在的路径.json")):
            self.assertEqual(grammar.load_cards(force=True), [])
        grammar.load_cards(force=True)  # 恢复真实卡库缓存，防污染后续用例（缓存是进程内全局）


# ---------------------------------------------------------------- 扫描归一化与句扫描

class TestNormalizeAndScan(unittest.TestCase):
    def test_normalize_punct_pad(self):
        self.assertEqual(grammar.normalize_for_scan("Bonjour ! Ça va ?"), " bonjour ça va ")

    def test_normalize_curly_apostrophe(self):
        self.assertEqual(
            grammar.normalize_for_scan("J\u2019ai un café."),
            " j'ai un café ",
        )

    def test_normalize_empty(self):
        self.assertEqual(grammar.normalize_for_scan("   "), " ")

    def test_scan_hits_contraction_card(self):
        ids = {c["id"] for c in grammar.find_cards_for_sentence("Je vais au cinéma ce soir.")}
        self.assertIn("gc_002", ids)

    def test_scan_hits_negation_card(self):
        ids = {c["id"] for c in grammar.find_cards_for_sentence("Je ne sais pas.")}
        self.assertIn("gc_004", ids)

    def test_scan_hits_il_y_a_card(self):
        ids = {c["id"] for c in grammar.find_cards_for_sentence("Il y a un café là-bas.")}
        self.assertIn("gc_048", ids)

    def test_scan_multi_hits_without_duplicates(self):
        cards = grammar.find_cards_for_sentence("Elle est allée au marché.")
        ids = [c["id"] for c in cards]
        self.assertIn("gc_042", ids)
        self.assertIn("gc_002", ids)  # au 缩合同句命中
        self.assertEqual(len(ids), len(set(ids)), "同句命中同卡必须去重")

    def test_scan_empty_and_digits(self):
        self.assertEqual(grammar.find_cards_for_sentence(""), [])
        self.assertEqual(grammar.find_cards_for_sentence("1234 5678"), [])


# ---------------------------------------------------------------- 规则标签器

class TestTagRule(unittest.TestCase):
    def test_negation_missing_ne(self):
        self.assertEqual(grammar.tag_error_rule("je sais pas", "je ne sais pas"), "negation")

    def test_article_merge_a_le(self):
        self.assertEqual(grammar.tag_error_rule("je vais a le cinema", "je vais au cinéma"), "article")

    def test_article_pair_de_des(self):
        self.assertEqual(grammar.tag_error_rule("je veux de pain", "je veux du pain"), "article")

    def test_gender_article_is_agreement(self):
        self.assertEqual(grammar.tag_error_rule("le gare", "la gare"), "agreement")
        self.assertEqual(grammar.tag_error_rule("un petite fille", "une petite fille"), "agreement")

    def test_conjugation_aux_plus_infinitive(self):
        self.assertEqual(grammar.tag_error_rule("je suis aller au cinéma", "je suis allé au cinéma"), "conjugation")

    def test_tense_hier_present(self):
        self.assertEqual(grammar.tag_error_rule("hier je parle au prof", "hier j'ai parlé au prof"), "tense")

    def test_preposition_country(self):
        self.assertEqual(grammar.tag_error_rule("je vais à France", "je vais en France"), "preposition")

    def test_agreement_tail_inflection(self):
        self.assertEqual(grammar.tag_error_rule("une voiture rouge", "une voiture rouge"), None)
        self.assertEqual(grammar.tag_error_rule("un voiture rouge", "une voiture rouge"), "agreement")
        self.assertEqual(grammar.tag_error_rule("elles sont content", "elles sont contentes"), "agreement")

    def test_unrecognizable_returns_none(self):
        self.assertEqual(grammar.tag_error_rule("bonjour", "bonjour !"), None)
        self.assertEqual(grammar.tag_error_rule("", "x"), None)
        self.assertEqual(grammar.tag_error_rule("abc", ""), None)

    def test_order_rule_priority_negation_first(self):
        # 重述同时补 ne 与改词尾 → negation 优先（规则序固化）
        self.assertEqual(grammar.tag_error_rule("elle est content", "elle n'est pas contente"), "negation")


# ---------------------------------------------------------------- on_recast 挂接（画像与推卡）

class TestOnRecast(unittest.TestCase):
    """db 层全 mock：log_error / tag_count / pick_card_for_tag。"""

    def setUp(self):
        self.card = grammar.card_public(grammar.load_cards()[0])
        patches = (
            mock.patch.object(grammar, "log_error", lambda *a, **k: None),
            mock.patch.object(grammar, "pick_card_for_tag", lambda *a, **k: dict(self.card)),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_no_recast_no_log(self):
        with mock.patch.object(grammar, "log_error") as mlog:
            self.assertIsNone(grammar.on_recast(1, "s1", "bonjour", FakeResult(None)))
            mlog.assert_not_called()

    def test_llm_tag_preferred(self):
        with (
            mock.patch.object(grammar, "log_error") as mlog,
            mock.patch.object(grammar, "tag_count", return_value=1),
        ):
            r = grammar.on_recast(1, "s1", "je sais pas", FakeResult("je ne sais pas", "negation"))
        self.assertIsNone(r)  # 计数 1 不推卡
        mlog.assert_called_once()
        self.assertEqual(mlog.call_args.args[1], "negation")
        self.assertEqual(mlog.call_args.args[2], "s1")
        self.assertEqual(mlog.call_args.args[5], "llm")

    def test_invalid_llm_tag_falls_back_to_rule(self):
        with (
            mock.patch.object(grammar, "log_error") as mlog,
            mock.patch.object(grammar, "tag_count", return_value=1),
        ):
            grammar.on_recast(1, "s1", "je suis aller", FakeResult("je suis allé", "verb_x"))
        self.assertEqual(mlog.call_args.args[1], "conjugation")
        self.assertEqual(mlog.call_args.args[5], "rule")

    def test_unrecognizable_error_not_logged(self):
        with mock.patch.object(grammar, "log_error") as mlog:
            self.assertIsNone(
                grammar.on_recast(1, "s1", "bonjour", FakeResult("bonjour !", None))
            )
            mlog.assert_not_called()

    def test_third_occurrence_pushes_card(self):
        with mock.patch.object(grammar, "tag_count", return_value=3):
            r = grammar.on_recast(1, "s1", "je sais pas", FakeResult("je ne sais pas", "negation"))
        self.assertIsNotNone(r)
        self.assertEqual(r["reason"], "third_time")
        self.assertEqual(r["count"], 3)
        self.assertEqual(r["tag"], "negation")
        self.assertIn("card", r)

    def test_fourth_occurrence_no_repush(self):
        with mock.patch.object(grammar, "tag_count", return_value=4):
            self.assertIsNone(grammar.on_recast(1, "s1", "je sais pas", FakeResult("je ne sais pas")))

    def test_second_occurrence_no_push(self):
        with mock.patch.object(grammar, "tag_count", return_value=2):
            self.assertIsNone(grammar.on_recast(1, "s1", "je sais pas", FakeResult("je ne sais pas")))

    def test_exception_swallowed(self):
        with mock.patch.object(grammar, "log_error", side_effect=RuntimeError("db down")):
            self.assertIsNone(grammar.on_recast(1, "s1", "je sais pas", FakeResult("je ne sais pas")))


# ---------------------------------------------------------------- profile 与端点

class TestProfileAndEndpoints(unittest.TestCase):
    def test_profile_suggest_only_when_count_reaches_threshold(self):
        tags_low = [{"tag": "article", "label": "冠词与缩合", "count": 2, "last_at": "t"}]
        tags_high = [{"tag": "article", "label": "冠词与缩合", "count": 5, "last_at": "t"}]
        card = grammar.card_public(grammar.load_cards()[0])
        with mock.patch.object(grammar, "error_profile", return_value=tags_low):
            self.assertIsNone(grammar.profile(1)["suggest"])
        with (
            mock.patch.object(grammar, "error_profile", return_value=tags_high),
            mock.patch.object(grammar, "pick_card_for_tag", return_value=dict(card)),
        ):
            suggest = grammar.profile(1)["suggest"]
        self.assertEqual(suggest["tag"], "article")
        self.assertEqual(suggest["card"]["id"], card["id"])

    def test_endpoint_cards_shape(self):
        data = _body(asyncio.run(grammar_router.grammar_cards()))
        self.assertEqual(data["total"], len(grammar.load_cards()))
        self.assertEqual(len(data["items"]), data["total"])
        first = data["items"][0]
        for key in ("id", "tag", "tag_label", "level", "title", "summary", "examples", "patterns"):
            self.assertIn(key, first)

    def test_endpoint_profile_uses_engine(self):
        with mock.patch.object(grammar_router.grammar_engine, "profile", return_value={"tags": [], "total": 0, "suggest": None}):
            data = _body(asyncio.run(grammar_router.grammar_profile()))
        self.assertEqual(data, {"tags": [], "total": 0, "suggest": None})


if __name__ == "__main__":
    unittest.main()
