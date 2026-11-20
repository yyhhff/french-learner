"""TASK-0067 v3.2 发音教练单测：词级对齐三维评分 + 选句器 + 路线 B 占位。

运行：cd backend && python -m unittest tests.test_pron_coach -v
零新增依赖（unittest 标准库）。
"""
import json
import unittest
from pathlib import Path

import pron_coach as pc

INPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "input"


def words_from(tokens, gap=0.25, dur=0.2):
    """构造词级时间戳序列。"""
    out = []
    for i, w in enumerate(tokens):
        out.append({
            "word": w,
            "start": round(i * gap, 3),
            "end": round(i * gap + dur, 3),
            "probability": 0.95,
        })
    return out


class TestScoring(unittest.TestCase):
    TARGET = "Je vais au magasin"

    def test_good_all_hit(self):
        r = pc.score_pronunciation(self.TARGET, words_from(["je", "vais", "au", "magasin"]))
        self.assertEqual(r["band"], "good")
        self.assertEqual(r["scores"]["content"], 100)
        self.assertEqual(r["missing_words"], [])

    def test_mid_missing_one(self):
        r = pc.score_pronunciation(self.TARGET, words_from(["je", "vais", "magasin"]))
        self.assertEqual(r["band"], "mid")
        self.assertIn("au", r["missing_words"])

    def test_poor_mostly_wrong(self):
        r = pc.score_pronunciation(self.TARGET, words_from(["je", "va", "maison"]))
        self.assertEqual(r["band"], "poor")
        self.assertGreaterEqual(r["scores"]["content"], 0)

    def test_three_bands_distinct(self):
        good = pc.score_pronunciation(self.TARGET, words_from(["je", "vais", "au", "magasin"]))["overall"]
        mid = pc.score_pronunciation(self.TARGET, words_from(["je", "vais", "magasin"]))["overall"]
        poor = pc.score_pronunciation(self.TARGET, words_from(["je", "va", "maison"]))["overall"]
        self.assertGreater(good, mid)
        self.assertGreater(mid, poor)

    def test_low_confidence_unsure(self):
        r = pc.score_pronunciation(self.TARGET, words_from(["je", "vais", "au", "magasin"]), low_confidence=True)
        self.assertEqual(r["band"], "UNSURE")
        self.assertIsNone(r["overall"])
        self.assertIsNone(r["scores"])

    def test_empty_is_unsure(self):
        r = pc.score_pronunciation(self.TARGET, [])
        self.assertEqual(r["band"], "UNSURE")
        self.assertEqual(r["reason"], "empty_text")

    def test_no_timestamps_neutral_dims(self):
        r = pc.score_pronunciation(self.TARGET, [{"word": w} for w in ["je", "vais", "au", "magasin"]])
        self.assertEqual(r["scores"]["fluency"], 60)
        self.assertEqual(r["scores"]["stability"], 60)

    def test_normalize_accents_and_apostrophe(self):
        self.assertEqual(pc.normalize_words("J'aime l'école !"), ["jaime", "lecole"])
        self.assertEqual(pc.normalize_words("Ça va très bien"), ["ca", "va", "tres", "bien"])

    def test_align_lcs(self):
        a = pc.align_words(["je", "vais", "au"], ["je", "va", "au"])
        self.assertEqual(a["matched"], 2)
        self.assertEqual(a["missing"], ["vais"])


class TestGopPlaceholder(unittest.TestCase):
    def test_gop_not_implemented(self):
        r = pc.score_gop()
        self.assertFalse(r["implemented"])
        self.assertEqual(r["band"], "UNSURE")


class TestSelector(unittest.TestCase):
    def test_focus_pool_100_valid(self):
        pool = pc._load_focus_pool()
        self.assertEqual(len(pool), 100)
        valid = {"y_vs_u", "nasal", "r", "elision", "liaison"}
        for s in pool:
            self.assertTrue(s["id"] and s["fr"])
            for tag in s["tags"]:
                self.assertIn(tag, valid)

    def test_select_all_focus_tags(self):
        for tag in ("y_vs_u", "nasal", "r", "elision", "liaison"):
            s = pc.select_sentence(focus_tag=tag, seed=7)
            self.assertIsNotNone(s)
            self.assertIn(tag, s["tags"])
            self.assertEqual(s["source"], "focus")

    def test_select_corpus_pool(self):
        s = pc.select_sentence(level="B2", seed=3)
        self.assertIsNotNone(s)
        self.assertIn(s["source"], ("focus", "corpus", "card"))

    def test_exclude_ids(self):
        first = pc.select_sentence(focus_tag="nasal", seed=1)
        second = pc.select_sentence(focus_tag="nasal", exclude_ids=[first["id"]], seed=1)
        self.assertNotEqual(first["id"], second["id"])

    def test_card_pool_dedup(self):
        cards = [{"id": 1, "example": "Je vais au magasin", "meaning": "我去商店",
                  "cefr_level": "A2", "word": "magasin"}]
        pool = pc._card_pool(cards)
        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0]["source"], "card")


if __name__ == "__main__":
    unittest.main()
