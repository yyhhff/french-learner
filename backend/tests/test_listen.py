"""TASK-0071 v3.1 听力强化单测：缩略形规则 + 听写挖空 + 判分归一。

运行：cd backend && python -m unittest tests.test_listen -v
零新增依赖（unittest 标准库）。
"""
import unittest

import reductions as rd
from routers.listen import (
    _normalize_answer,
    _tokens_and_words,
    pick_blank_indices,
)


class TestReductions(unittest.TestCase):
    def test_je_ne(self):
        self.assertEqual(rd.reduce_sentence("Je ne sais pas"), "J'sais pas")

    def test_generic_ne_drop(self):
        # tu 吞音 + ne 脱落：口语真实形态 t'comprends pas
        self.assertEqual(rd.reduce_sentence("tu ne comprends pas"), "t'comprends pas")
        self.assertEqual(rd.reduce_sentence("Il ne pleut pas"), "Il pleut pas")

    def test_tu_elision(self):
        self.assertEqual(rd.reduce_sentence("tu es là"), "t'es là")
        self.assertEqual(rd.reduce_sentence("Tu as raison"), "T'as raison")
        self.assertEqual(rd.reduce_sentence("tu sais"), "t'sais")

    def test_je_consonant(self):
        self.assertEqual(rd.reduce_sentence("je pense"), "j'pense")
        self.assertEqual(rd.reduce_sentence("Je veux bien"), "J'veux bien")

    def test_mts_elision(self):
        self.assertEqual(rd.reduce_sentence("me trompe"), "m'trompe")
        self.assertEqual(rd.reduce_sentence("il se lève"), "il s'lève")
        # 元音前是标准省音，不在口语规则处理范围
        self.assertEqual(rd.reduce_sentence("m'appelle"), "m'appelle")

    def test_fixed_phrases(self):
        self.assertEqual(rd.reduce_sentence("il y a"), "y'a")
        self.assertEqual(rd.reduce_sentence("Il y en a beaucoup"), "Y'en a beaucoup")
        self.assertEqual(rd.reduce_sentence("parce que"), "parc'que")
        self.assertEqual(rd.reduce_sentence("ce que je veux"), "c'que j'veux")
        self.assertEqual(rd.reduce_sentence("ce qui reste"), "c'qui reste")

    def test_idempotent(self):
        once = rd.reduce_sentence("Je ne sais pas ce que tu veux")
        self.assertEqual(rd.reduce_sentence(once), once)

    def test_no_word_internal_damage(self):
        # \b 保证不误伤词内字母
        self.assertEqual(rd.reduce_sentence("nouvelle négligence"), "nouvelle négligence")

    def test_empty(self):
        self.assertEqual(rd.reduce_sentence(""), "")
        self.assertEqual(rd.reduce_sentence(None), "")


class TestTokenize(unittest.TestCase):
    """展示 tokens 与判分 words 等长同序（挖空下标共用）。"""

    def test_parallel_lists(self):
        toks, words = _tokens_and_words("Je vais au marché.")
        self.assertEqual(toks, ["Je", "vais", "au", "marché."])
        self.assertEqual(words, ["Je", "vais", "au", "marché"])

    def test_punct_only_token_kept_in_tokens(self):
        toks, words = _tokens_and_words("Bonjour ?")
        self.assertEqual(toks, ["Bonjour", "?"])
        self.assertEqual(words, ["Bonjour", ""])  # 纯标点在 words 里为空串，不会成为挖空

    def test_internal_apostrophe_kept(self):
        toks, words = _tokens_and_words("Qu'un seul l'homme")
        self.assertEqual(toks, ["Qu'un", "seul", "l'homme"])
        self.assertEqual(words, ["Qu'un", "seul", "l'homme"])

    def test_same_length(self):
        toks, words = _tokens_and_words("Oh, tu as dû partir hier, hein ?")
        self.assertEqual(len(toks), len(words))

    def test_empty(self):
        self.assertEqual(_tokens_and_words(""), ([], []))


class TestBlanks(unittest.TestCase):
    WORDS = ["Je", "vais", "au", "marché", "avec", "Marie", "demain"]

    def test_deterministic(self):
        a = pick_blank_indices(self.WORDS, "A1", "t1:1:2026-11-21")
        b = pick_blank_indices(self.WORDS, "A1", "t1:1:2026-11-21")
        self.assertEqual(a, b)

    def test_level_counts(self):
        self.assertEqual(len(pick_blank_indices(self.WORDS, "A1", "s1")), 1)
        self.assertEqual(len(pick_blank_indices(self.WORDS, "A2", "s2")), 2)
        self.assertEqual(len(pick_blank_indices(self.WORDS, "B1", "s3")), 3)

    def test_prefers_content_words(self):
        idx = pick_blank_indices(self.WORDS, "B1", "s4")
        picked = [self.WORDS[i].lower() for i in idx]
        self.assertNotIn("au", picked)  # 虚词不挖

    def test_short_line_no_blanks(self):
        self.assertEqual(pick_blank_indices(["oui"], "A1", "s5"), [])
        self.assertEqual(pick_blank_indices(["je", "sais"], "A1", "s6"), [])

    def test_fallback_when_all_stopwords(self):
        idx = pick_blank_indices(["le", "chat", "dort"], "A1", "s7")
        self.assertEqual(len(idx), 1)


class TestJudge(unittest.TestCase):
    def test_accent_insensitive(self):
        self.assertEqual(_normalize_answer("marché"), _normalize_answer("marche"))
        self.assertEqual(_normalize_answer("père"), _normalize_answer("pere"))

    def test_case_and_punct_insensitive(self):
        self.assertEqual(_normalize_answer("Marie."), _normalize_answer("marie"))
        self.assertNotEqual(_normalize_answer("chat"), _normalize_answer("chien"))

    def test_empty_counts_wrong(self):
        self.assertNotEqual(_normalize_answer(""), _normalize_answer("mot"))


if __name__ == "__main__":
    unittest.main()
