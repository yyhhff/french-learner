"""v3.2 发音教练核心（TASK-0067）：选句器 + 词级对齐三维评分。

设计边界（MASTER_PLAN §1 定稿决策）：
- 发音评分走「转写对齐」路线 A；路线 B（GOP 音素级）只留接口 score_gop()，本期不实现。
- 选句器三池：语料逐句（texts.json）+ 词卡例句（db.list_cards，运行时注入）+ 难点句库（pron_coach_focus.json）。
  实现重心是选句器，不动态生成、不新增审校负担。
- 低置信（ASR 三道门控 low_confidence）→ UNSURE，不评分不误判（沿用 TASK-0031 红线）。
- 不存音频、不存转写文本（隐私）；纯函数，app.py 只装配路由。

零新增依赖：标准库 json/re/statistics/unicodedata。
"""
from __future__ import annotations

import json
import logging
import random
import re
import statistics
import unicodedata
from pathlib import Path

logger = logging.getLogger("yaya.pron_coach")

INPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "input"
TEXTS_FILE = INPUT_DIR / "texts.json"
FOCUS_FILE = INPUT_DIR / "pron_coach_focus.json"

VALID_TAGS = ("y_vs_u", "nasal", "r", "elision", "liaison")
VALID_LEVELS = ("A1", "A2", "B1", "B2")
LOW_CONF_BAND = "UNSURE"

# 进程内缓存
_TEXTS_CACHE = None   # list[CoachSentence] 语料逐句池
_FOCUS_CACHE = None   # list[CoachSentence] 难点句库


# ---------------------------------------------------------------- 文本归一化

def normalize_words(text: str) -> list[str]:
    """法语句 → 归一化词表：NFD 去重音、小写、只保留字母数字，撇号视为词内连接。

    例：「J'aime l'école !」→ ['jaime', 'lecole']
    去重视觉差异（é/e）便于对齐；保留 'aime/école' 词形供词级比对。
    """
    if not text:
        return []
    decomposed = unicodedata.normalize("NFD", str(text))
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    stripped = stripped.lower().replace("'", "").replace("\u2019", "")
    tokens = re.findall(r"[a-z0-9]+", stripped)
    return tokens


def _norm_key(word: str) -> str:
    """单个词归一化为可比对 key（供未命中词定位）。"""
    return "".join(normalize_words(word))


# ---------------------------------------------------------------- 词级对齐

def align_words(target: list[str], heard: list[str]) -> dict:
    """词级 LCS 对齐：返回命中数、命中位置、目标端缺失词、多余词。

    用经典 LCS 动态规划（O(mn)，句子级 m,n<40，代价可忽略）。
    返回：
      matched      命中词数
      target_hits  目标各位置是否命中（list[bool]）
      missing      目标端未命中词（按目标顺序，去重保序）
      extra        转写多出的词（ASR 幻觉/填充）
    """
    m, n = len(target), len(heard)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            dp[i][j] = dp[i - 1][j - 1] + 1 if target[i - 1] == heard[j - 1] else max(dp[i - 1][j], dp[i][j - 1])

    hits = [False] * m
    i, j = m, n
    while i > 0 and j > 0:
        if target[i - 1] == heard[j - 1]:
            hits[i - 1] = True
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1

    missing, seen = [], set()
    for k, hit in enumerate(hits):
        if not hit and target[k] not in seen:
            seen.add(target[k])
            missing.append(target[k])

    matched = sum(hits)
    # 转写多出的词：heard 中未参与 LCS 匹配的（用命中词 multiset 近似剔除）
    hit_words = [target[k] for k, hit in enumerate(hits) if hit]
    extra_pool = list(heard)
    extra = []
    for w in hit_words:
        if w in extra_pool:
            extra_pool.remove(w)
    extra = extra_pool
    return {"matched": matched, "target_hits": hits, "missing": missing, "extra": extra}


# ---------------------------------------------------------------- 三维评分

def score_pronunciation(target_text: str, words: list[dict], low_confidence: bool = False) -> dict:
    """路线 A：基于词级时间戳的三维评分。

    参数：
      target_text    目标句（法语原文，含重音/撇号）
      words          ASR 词级数组 [{word,start,end,probability}]
      low_confidence ASR 低置信门控标记

    返回 dict：
      band              'good' | 'mid' | 'poor' | 'UNSURE'
      scores            {content, fluency, stability} 各 0-100
      overall           综合 0-100（UNSURE 时为 None，不评分）
      hit_words         目标中命中的原词（按目标顺序）
      missing_words     目标中未命中的原词（中文反馈定位用）
      reason            UNSURE 原因 / 评分说明
    """
    if low_confidence:
        return {
            "band": LOW_CONF_BAND, "scores": None, "overall": None,
            "hit_words": [], "missing_words": [], "reason": "low_confidence",
        }

    target_norm = normalize_words(target_text)
    # ASR 的 words 中 word 字段常带前导空格，且可能含标点，统一归一化
    heard_norm: list[str] = []
    for w in words or []:
        heard_norm.extend(normalize_words(w.get("word", "")))

    if not target_norm or not heard_norm:
        return {
            "band": LOW_CONF_BAND, "scores": None, "overall": None,
            "hit_words": [], "missing_words": [], "reason": "empty_text",
        }

    alignment = align_words(target_norm, heard_norm)
    matched = alignment["matched"]
    m = len(target_norm)

    # 维度 1：内容命中率 = 命中词 / 目标词
    content = round(100.0 * matched / m)

    # 把目标词表按归一化顺序映射回原词（供命中/缺失反馈）
    target_originals = re.findall(r"[^\s]+", re.sub(r"[!?.,;:]+", "", target_text or ""))
    if len(target_originals) != m:
        target_originals = target_norm  # 长度对不上时退回归一化词

    hit_words, missing_words = [], []
    for k, hit in enumerate(alignment["target_hits"]):
        origin = target_originals[k] if k < len(target_originals) else target_norm[k]
        (hit_words if hit else missing_words).append(origin)

    # 维度 2/3 依赖词级时间戳；缺时间戳时不给维度分（降权到内容单一维度）
    timed = [w for w in (words or []) if w.get("start") is not None and w.get("end") is not None]
    if len(timed) >= 2:
        # 有效词时长（>0）与词间隙
        durations = [max(0.0, float(w["end"]) - float(w["start"])) for w in timed]
        starts = [float(w["start"]) for w in timed]
        gaps = [max(0.0, starts[k + 1] - float(timed[k]["end"])) for k in range(len(timed) - 1)]
        speech_span = max(float(timed[-1]["end"]) - float(timed[0]["start"]), 0.001)
        wpm = round(60.0 * len(timed) / speech_span)

        # 流利度：停顿次数（gap>0.35s 记为一次停顿）+ 语速偏离（法语舒适区间 90-160 wpm）
        pauses = sum(1 for g in gaps if g > 0.35)
        pause_penalty = min(40, pauses * 12)
        if 90 <= wpm <= 160:
            speed_penalty = 0
        elif wpm < 90:
            speed_penalty = min(30, int((90 - wpm) / 3))
        else:
            speed_penalty = min(30, int((wpm - 160) / 6))
        fluency = max(0, 100 - pause_penalty - speed_penalty)

        # 稳定度：词时长变异系数（CV=标准差/均值），越小越稳定
        mean_dur = statistics.fmean(durations) if durations else 0.0
        if mean_dur > 0 and len(durations) >= 2:
            cv = statistics.pstdev(durations) / mean_dur
            stability = max(0, round(100 - cv * 60))
        else:
            stability = 50
        timing_note = {"wpm": wpm, "pauses": pauses}
    else:
        # 无词级时间戳：只给内容分，流利度/稳定度给中性分并在 reason 标注
        fluency, stability, timing_note = 60, 60, {"note": "no_word_timestamps"}

    scores = {"content": content, "fluency": int(fluency), "stability": int(stability)}
    overall = round(content * 0.5 + int(fluency) * 0.25 + int(stability) * 0.25)

    # 内容命中率是主维度：内容不过关时，流利度/稳定度再高也不判 good（防漏词被掩盖）
    if content >= 85 and overall >= 75:
        band = "good"
    elif content >= 50 and overall >= 50:
        band = "mid"
    else:
        band = "poor"

    return {
        "band": band,
        "scores": scores,
        "overall": overall,
        "hit_words": hit_words,
        "missing_words": missing_words,
        "reason": "ok",
        "timing": timing_note,
    }


def score_gop(*args, **kwargs) -> dict:
    """路线 B（强制对齐 GOP 音素级评分）占位接口——本期不实现（MASTER_PLAN §1）。

    保留函数签名以便未来接入 torch 系强制对齐模型；调用即返回明确未实现，
    不抛异常，避免前端因误调崩溃。真实接入需单独立项（引入音素级依赖）。
    """
    return {
        "implemented": False,
        "band": LOW_CONF_BAND,
        "reason": "GOP（路线 B）本期未实现，当前使用转写对齐路线 A",
    }


# ---------------------------------------------------------------- 中文反馈

def build_feedback(score: dict, sentence: dict | None = None) -> dict:
    """把评分结果 + 句子中文 → 温和中文反馈（PM 口径：不判错、指出未命中词）。

    返回 {title, detail, cls}；cls ∈ ok/retry/unsure 供前端配色。
    """
    if score.get("band") == LOW_CONF_BAND:
        return {
            "title": "这次没太听清，可能是收音的小问题～",
            "detail": "再来一次就好，多听几遍示范也一样在进步。",
            "cls": "unsure",
        }

    missing = score.get("missing_words") or []
    zh_map = {}
    if sentence:
        focus = sentence.get("focus_word")
        if focus:
            zh_map[_norm_key(focus)] = sentence.get("cn", "")
        # 词卡/难点库的整句中文作为整体提示
    missing_detail = ""
    if missing:
        shown = "、".join(missing[:4])
        if sentence and sentence.get("cn"):
            missing_detail = f"这几个词再练练：{shown}。整句意思是「{sentence['cn']}」。"
        else:
            missing_detail = f"这几个词再练练：{shown}。"

    band = score.get("band")
    if band == "good":
        return {
            "title": "发音很棒，节奏也稳！",
            "detail": missing_detail or "继续保持，试试更长的句子吧～",
            "cls": "ok",
        }
    if band == "mid":
        return {
            "title": "挺不错的，再顺一顺就更自然啦～",
            "detail": missing_detail or "再听一遍示范，跟着模仿就好～",
            "cls": "ok",
        }
    return {
        "title": "想再听一遍示范吗？再试一次就好～",
        "detail": missing_detail or "慢慢来，一个词一个词跟着读。",
        "cls": "retry",
    }


# ---------------------------------------------------------------- 选句器（三池）

def _load_texts_pool() -> list[dict]:
    """语料逐句池：从 texts.json 的每篇 lines 提取，主池（186+ 句，v2.3 后自动扩池）。"""
    global _TEXTS_CACHE
    if _TEXTS_CACHE is not None:
        return _TEXTS_CACHE
    pool: list[dict] = []
    try:
        with TEXTS_FILE.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        for text in payload.get("texts", []):
            level = text.get("cefr_level", "")
            for line in text.get("lines", []):
                fr = (line.get("fr") or "").strip()
                cn = (line.get("cn") or "").strip()
                if not fr:
                    continue
                pool.append({
                    "id": f"{text.get('id', 'txt')}_{line.get('seq', 0)}",
                    "fr": fr, "cn": cn, "cefr": level,
                    "tags": [f"src:{text.get('topic', '')}"],  # 语料池标签=主题，非发音难点
                    "focus_word": "", "source": "corpus",
                })
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("语料池加载失败：%s", exc)
    _TEXTS_CACHE = pool
    return pool


def _load_focus_pool() -> list[dict]:
    """难点句库池：100 句手写，标签化聚焦发音难点。"""
    global _FOCUS_CACHE
    if _FOCUS_CACHE is not None:
        return _FOCUS_CACHE
    pool: list[dict] = []
    try:
        with FOCUS_FILE.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        for s in payload.get("sentences", []):
            if not (s.get("fr") and s.get("id")):
                continue
            pool.append({
                "id": s["id"], "fr": s["fr"], "cn": s.get("cn", ""),
                "cefr": s.get("cefr", ""), "tags": list(s.get("tags", [])),
                "focus_word": s.get("focus_word", ""), "source": "focus",
            })
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("难点句库加载失败：%s", exc)
    _FOCUS_CACHE = pool
    return pool


def _card_pool(cards: list[dict]) -> list[dict]:
    """词卡例句池：从运行时注入的 db.list_cards() 提取 example（157 句），补充池。

    example 的中文是词级 meaning（非整句翻译），故 cn 取 meaning；
    反馈以语料池/难点库为主，此池仅在标签/等级过滤后作补充。
    """
    pool: list[dict] = []
    for card in cards or []:
        ex = (card.get("example") or "").strip()
        if not ex:
            continue
        pool.append({
            "id": f"card_{card.get('id', '')}", "fr": ex,
            "cn": card.get("meaning", ""), "cefr": card.get("cefr_level", ""),
            "tags": [], "focus_word": card.get("word", ""), "source": "card",
        })
    return pool


def _norm_sentence(fr: str) -> str:
    """句子级归一化键，用于跨池去重。"""
    return " ".join(normalize_words(fr))


def select_sentence(
    level: str | None = None,
    focus_tag: str | None = None,
    exclude_ids: list[str] | None = None,
    cards: list[dict] | None = None,
    seed: int | None = None,
) -> dict | None:
    """三池选句器：难点标签优先 → 等级匹配 → 跨池去重 → 随机取一。

    参数：
      level       'A1'/'A2'/'B1'/'B2' 或 None（不限）
      focus_tag   发音难点标签（y_vs_u/nasal/r/elision/liaison）或 None
      exclude_ids 已练过的 id 列表（避免重复）
      cards       词卡列表（来自 db.list_cards()），注入词卡池
      seed        随机种子（单测可复现）

    返回 CoachSentence dict 或 None（池空）。
    """
    exclude = set(exclude_ids or [])
    if level is not None and level not in VALID_LEVELS:
        level = None
    if focus_tag is not None and focus_tag not in VALID_TAGS:
        focus_tag = None

    focus_pool = _load_focus_pool()
    corpus_pool = _load_texts_pool()
    card_pool = _card_pool(cards)

    def eligible(pool: list[dict]) -> list[dict]:
        return [
            s for s in pool
            if s["id"] not in exclude
            and (not level or s["cefr"] == level)
            and (not focus_tag or focus_tag in s["tags"])
        ]

    # 优先级：带发音标签的难点池 → 语料池 → 词卡池（词卡池去重后补充）
    focus_hits = eligible(focus_pool)
    corpus_hits = eligible(corpus_pool)
    seen_keys = {_norm_sentence(s["fr"]) for s in focus_hits + corpus_hits}
    card_hits = [s for s in eligible(card_pool) if _norm_sentence(s["fr"]) not in seen_keys]

    chosen_pool = None
    if focus_hits:
        chosen_pool = focus_hits
    elif corpus_hits:
        chosen_pool = corpus_hits
    elif card_hits:
        chosen_pool = card_hits
    if not chosen_pool:
        return None

    rng = random.Random(seed)
    return dict(rng.choice(chosen_pool))
