"""v3.3 语法的针脚：语法微卡引擎（加载 / 句扫描 / 错误标签 / 画像 / 推卡）。

契约（docs/MASTER_PLAN.md v3.3 详案 + TASK-0078）：
- data/input/grammar_cards.json：50 卡手写原创，进程内缓存，改动需重启同步
  （沿 assessment.py 的 INPUT_FILE 惯例）。
- 新表 grammar_error_log 在本模块内 CREATE TABLE IF NOT EXISTS，不动 db.py 公共区。
- 错误标签双路：GLM error_tag（ai.py 契约 v3.3 扩展，可选第 5 键）优先，
  规则标签器 tag_error_rule() 兜底；都判不出 → 不落标签不推卡（诚实降级）。
- 对 chat.py 暴露 on_recast()（内部吞异常，绝不阻塞对话主流程）；
  对 routers/grammar.py 暴露 load_cards() / card_public() / profile()。
- 扫描归一化 normalize_for_scan()：小写 + 标点转空格 + 空白压缩 + 首尾补空格。
  卡片 patterns 一律按「空格包裹的词/短语」书写，避免 \\b 在 JS 里对带重音
  字符失效（é 不是 \\w）；前端 grammar.js 用同一算法（两份实现，py 侧由单测固化）。
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional

import db

logger = logging.getLogger("yaya.grammar")

INPUT_FILE = (
    Path(__file__).resolve().parent.parent / "data" / "input" / "grammar_cards.json"
)

# 错误标签总表（与 ai.py SYSTEM_PROMPT 中的固定标签集一致，10 类）
ERROR_TAGS = {
    "agreement": "性数配合",
    "conjugation": "动词变位",
    "tense": "时态选择",
    "article": "冠词与缩合",
    "preposition": "介词",
    "negation": "否定",
    "pronoun": "代词",
    "question": "疑问句",
    "word_order": "语序",
    "lexical": "用词搭配",
}
LEVELS = ("A1", "A2", "B1", "B2")

# 同类错误自动推卡的门槛（总纲 v3.3：同类 recast 错误第 3 次出现）
PUSH_THRESHOLD = 3

_PUNCT_RE = re.compile(r"[.,!?;:«»]")
_SPACE_RE = re.compile(r"\s+")


def normalize_for_scan(text: str) -> str:
    """扫描归一化：小写 + 标点替换为空格 + 空白压缩 + 首尾补空格。"""
    s = (text or "").lower().replace("\u2019", "'")
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    return f" {s} " if s else " "


# ---------------------------------------------------------------- 卡片加载与校验

_cards_cache: Optional[list] = None


def load_cards(force: bool = False) -> list:
    """读卡库（进程内缓存）；文件缺失/损坏降级为空列表，不让服务崩。"""
    global _cards_cache
    if _cards_cache is not None and not force:
        return _cards_cache
    try:
        with INPUT_FILE.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError) as exc:
        logger.warning("语法卡库文件不可用：%s（%s）", INPUT_FILE, exc)
        _cards_cache = []
        return _cards_cache
    raw = payload.get("cards") if isinstance(payload, dict) else None
    _cards_cache = [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []
    return _cards_cache


def validate_cards(cards: Optional[list] = None) -> list:
    """schema 校验（单测/自检用）：返回问题列表，空列表 = 全部通过。"""
    problems: list = []
    cards = load_cards() if cards is None else cards
    seen = set()
    for i, c in enumerate(cards):
        cid = c.get("id")
        if not (isinstance(cid, str) and cid.strip()):
            problems.append(f"#{i}: id 缺失")
            continue
        if cid in seen:
            problems.append(f"{cid}: id 重复")
        seen.add(cid)
        if c.get("tag") not in ERROR_TAGS:
            problems.append(f"{cid}: tag 非法 {c.get('tag')!r}")
        if c.get("level") not in LEVELS:
            problems.append(f"{cid}: level 非法 {c.get('level')!r}")
        if not (isinstance(c.get("title"), str) and c["title"].strip()):
            problems.append(f"{cid}: title 缺失")
        if not (isinstance(c.get("summary"), str) and c["summary"].strip()):
            problems.append(f"{cid}: summary 缺失")
        examples = c.get("examples")
        if not (isinstance(examples, list) and 1 <= len(examples) <= 3):
            problems.append(f"{cid}: examples 须 1..3 条")
            continue
        for j, ex in enumerate(examples):
            if not (
                isinstance(ex, dict)
                and isinstance(ex.get("fr"), str)
                and ex["fr"].strip()
                and isinstance(ex.get("cn"), str)
                and ex["cn"].strip()
            ):
                problems.append(f"{cid}: examples[{j}] 缺 fr/cn")
        patterns = c.get("patterns")
        if not (isinstance(patterns, list) and patterns):
            problems.append(f"{cid}: patterns 缺失")
            continue
        for p in patterns:
            if not (isinstance(p, str) and p.strip()):
                problems.append(f"{cid}: pattern 非空字符串缺失")
                continue
            try:
                re.compile(p)
            except re.error as exc:
                problems.append(f"{cid}: pattern 编译失败 {p!r}（{exc}）")
    return problems


def card_public(c: dict) -> dict:
    """面客字段（含 patterns：前端本地句扫描需要，非敏感）。"""
    return {
        "id": c.get("id"),
        "tag": c.get("tag"),
        "tag_label": ERROR_TAGS.get(c.get("tag"), ""),
        "level": c.get("level"),
        "title": c.get("title"),
        "summary": c.get("summary"),
        "examples": c.get("examples") or [],
        "patterns": c.get("patterns") or [],
    }


def find_cards_for_sentence(text: str, cards: Optional[list] = None) -> list:
    """句级扫描：返回命中语法卡（按 id 去重、保持库内顺序）。

    patterns 是「提示性入口」非判定——多命中只是多一个入口，不阻塞阅读。
    """
    if not (isinstance(text, str) and text.strip()):
        return []
    hay = normalize_for_scan(text)
    if hay == " ":
        return []
    out: list = []
    seen: set = set()
    for c in (load_cards() if cards is None else cards):
        for p in c.get("patterns") or []:
            try:
                if re.search(p, hay):
                    if c.get("id") not in seen:
                        seen.add(c.get("id"))
                        out.append(c)
                    break
            except re.error:
                continue
    return out


# ---------------------------------------------------------------- 规则标签器（GLM 降级兜底）
# 只覆盖高频、模式明确的错误类（precision 优先）；判不出 → None（诚实降级）。
# 只在 Python 侧运行，可用 \b（Python re 的 \w 含重音字母，与 JS 不同）。

# 否定：重述里有 ne / n'（省音）、原句没有 → 否定类错误
_RULE_NEG_RECAST = re.compile(r"\bne\b|\bn'[a-zà-öø-ÿ]", re.IGNORECASE)
_RULE_NEG_USER = re.compile(r"\bne\b|\bn'[a-zà-öø-ÿ]", re.IGNORECASE)
# 冠词缩合：原句 a/de 后直跟 le/les（应缩成 au/aux、du/des）
_RULE_ARTICLE_MERGE = re.compile(r"\b(a|de)\s+(le|les)\b", re.IGNORECASE)
# 缩合/复数冠词对：du↔de la、au↔aux、de↔des/d↔du（article 类）
_RULE_ARTICLE_PAIRS = {
    ("du", "de la"), ("de la", "du"), ("au", "aux"), ("aux", "au"),
    ("de", "des"), ("des", "de"), ("de", "du"), ("du", "de"),
}
# 性别类限定词对：le↔la、un↔une、mon↔ma 等（本质是名词性别，归 agreement，
# 与 GLM 标签口径一致——『gare 是阴性用 la』是性数配合而非冠词缩合）
_RULE_GENDER_PAIRS = {
    ("le", "la"), ("la", "le"), ("un", "une"), ("une", "un"),
    ("mon", "ma"), ("ma", "mon"), ("ton", "ta"), ("ta", "ton"),
    ("son", "sa"), ("sa", "son"), ("ce", "cette"), ("cette", "ce"),
}
# être/avoir + 动词原形（应为过去分词或位置错位）：je suis aller → conjugation
_RULE_AUX_INF = re.compile(
    r"\b(suis|es|est|sommes|êtes|sont|ai|as|a|avons|avez|ont)\s+"
    r"(aller|faire|parler|manger|finir|voir|prendre|partir|venir|dormir|savoir|pouvoir|vouloir)\b",
    re.IGNORECASE,
)
# 时间标记 + 一般现在时（应为过去时态）：hier je vais → tense
_RULE_TENSE_HIER = re.compile(
    r"\b(hier|avant-hier|la semaine dernière|l'année dernière|le mois dernier)\b.*"
    r"\b(je|tu|il|elle|on|nous|vous|ils|elles)\s+\w+(?:e|es|ons|ez|ent)\b",
    re.IGNORECASE | re.DOTALL,
)
# 国家介词：à + 阴性国家名（应为 en）
_RULE_PREP_COUNTRY = re.compile(
    r"\bà\s+(France|Chine|Espagne|Italie|Allemagne|Angleterre|Belgique|Suisse|Amérique|Corée|Grèce)\b",
    re.IGNORECASE,
)

_TOKEN_RE = re.compile(r"[a-zà-öø-ÿæœ']+")


def _stem_tail(w: str) -> str:
    """剥掉词尾的复数/阴形屈折（es / s / e），用于形态差异判定。"""
    for suf in ("es", "s", "e"):
        if len(w) > 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _looks_agreement(user_text: str, recast_text: str) -> bool:
    """等长 token 逐一对比，所有差异都只是词尾屈折（-e/-s/-es）→ 性数配合。"""
    a = _TOKEN_RE.findall((user_text or "").lower())
    b = _TOKEN_RE.findall((recast_text or "").lower())
    if not a or not b or len(a) != len(b):
        return False
    diffs = [(x, y) for x, y in zip(a, b) if x != y]
    if not diffs:
        return False
    return all(_stem_tail(x) == _stem_tail(y) for x, y in diffs)


def tag_error_rule(user_text: str, recast_text: str) -> Optional[str]:
    """规则标签器：user_text（含错原句）vs recast_text（正确重述）→ 标签或 None。"""
    if not (isinstance(user_text, str) and user_text.strip()):
        return None
    if not (isinstance(recast_text, str) and recast_text.strip()):
        return None
    low_user = user_text.lower()
    low_recast = recast_text.lower()

    # 1. 否定：重述补了 ne / n'（省音），原句没有
    if _RULE_NEG_RECAST.search(low_recast) and not _RULE_NEG_USER.search(low_user):
        return "negation"
    # 2. 冠词缩合：a/de + le/les 应缩合
    if _RULE_ARTICLE_MERGE.search(low_user):
        return "article"
    # 3. 单 token 替换：缩合/复数冠词对 → article；性别类限定词对 → agreement
    user_toks = _TOKEN_RE.findall(low_user)
    recast_toks = _TOKEN_RE.findall(low_recast)
    if len(user_toks) == len(recast_toks):
        swapped = [(x, y) for x, y in zip(user_toks, recast_toks) if x != y]
        if len(swapped) == 1:
            pair = (swapped[0][0], swapped[0][1])
            if pair in _RULE_ARTICLE_PAIRS:
                return "article"
            if pair in _RULE_GENDER_PAIRS:
                return "agreement"
    # 4. être/avoir + 原形 → 变位
    if _RULE_AUX_INF.search(low_user):
        return "conjugation"
    # 5. 时间标记 + 一般现在时 → 时态
    if _RULE_TENSE_HIER.search(low_user):
        return "tense"
    # 6. à + 阴性国家 → 介词
    if _RULE_PREP_COUNTRY.search(low_user):
        return "preposition"
    # 7. 词尾屈折差异 → 性数配合
    if _looks_agreement(user_text, recast_text):
        return "agreement"
    return None


# ---------------------------------------------------------------- 画像与推卡（新表 grammar_error_log）

_TABLE_READY = False

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS grammar_error_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    scene_id TEXT,
    user_text TEXT,
    recast_text TEXT,
    source TEXT,
    created_at TEXT NOT NULL
)
"""


def _ensure_table() -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return
    conn = db.get_conn()
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()
        _TABLE_READY = True
    finally:
        conn.close()


def log_error(
    user_id: int,
    tag: str,
    scene_id: Optional[str],
    user_text: str,
    recast_text: str,
    source: str,
) -> None:
    _ensure_table()
    conn = db.get_conn()
    try:
        conn.execute(
            "INSERT INTO grammar_error_log "
            "(user_id, tag, scene_id, user_text, recast_text, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, tag, scene_id, user_text, recast_text, source, db.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def tag_count(user_id: int, tag: str) -> int:
    _ensure_table()
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM grammar_error_log WHERE user_id = ? AND tag = ?",
            (user_id, tag),
        ).fetchone()
        return int(row["n"]) if row else 0
    finally:
        conn.close()


def error_profile(user_id: int = db.DEFAULT_USER_ID) -> list:
    """错误画像：按标签计数 + 最近一次日期，多者在前。"""
    _ensure_table()
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT tag, COUNT(*) AS n, MAX(created_at) AS last_at "
            "FROM grammar_error_log WHERE user_id = ? GROUP BY tag ORDER BY n DESC, last_at DESC",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        tag = r["tag"]
        if tag not in ERROR_TAGS:
            continue  # 历史脏数据隔离
        out.append(
            {
                "tag": tag,
                "label": ERROR_TAGS[tag],
                "count": int(r["n"]),
                "last_at": r["last_at"],
            }
        )
    return out


def pick_card_for_tag(user_id: int, tag: str, cards: Optional[list] = None) -> Optional[dict]:
    """按标签挑卡：优先与用户 CEFR 同级，无则取该标签最低级别第一张。"""
    pool = [c for c in (load_cards() if cards is None else cards) if c.get("tag") == tag]
    if not pool:
        return None
    level = None
    try:
        prof = db.get_profile(user_id) or {}
        level = prof.get("cefr_level")
    except Exception:
        level = None
    same = [c for c in pool if c.get("level") == level] if level in LEVELS else []
    if same:
        return same[0]
    for lv in LEVELS:
        lower = [c for c in pool if c.get("level") == lv]
        if lower:
            return lower[0]
    return pool[0]


def on_recast(
    user_id: int, scene_id: Optional[str], user_text: str, result
) -> Optional[dict]:
    """chat.py 挂接点：recast 纠错轮记录画像；同类第 3 次 → 返回推卡 payload。

    - 标签双路：result.error_tag（GLM 契约字段，已在模块内校验合法性）优先，
      规则标签器兜底；两者都判不出 → 只记轮不推卡。
    - 只在计数恰为 PUSH_THRESHOLD 时推一次（第 4 次起不重推）。
    - 任何异常吞掉返回 None——语法增强绝不阻塞对话主流程。
    """
    try:
        recast_of = getattr(result, "recast_of", None)
        if not (isinstance(recast_of, str) and recast_of.strip()):
            return None
        tag = getattr(result, "error_tag", None)
        source = "llm"
        if tag not in ERROR_TAGS:
            tag = tag_error_rule(user_text, recast_of)
            source = "rule"
        if tag is None:
            return None
        log_error(user_id, tag, scene_id, user_text, recast_of, source)
        count = tag_count(user_id, tag)
        if count != PUSH_THRESHOLD:
            return None
        card = pick_card_for_tag(user_id, tag)
        if not card:
            return None
        return {
            "card": card_public(card),
            "tag": tag,
            "tag_label": ERROR_TAGS[tag],
            "count": count,
            "reason": "third_time",
        }
    except Exception as exc:  # 防御性：画像是增益，主链路不可断
        logger.warning("语法画像记录/推卡失败（忽略）：%s", exc)
        return None


def profile(user_id: int = db.DEFAULT_USER_ID) -> dict:
    """GET /api/grammar/profile：错误画像 + 建议卡（review.js banner 消费）。"""
    tags = error_profile(user_id)
    suggest = None
    for t in tags:
        if t["count"] >= PUSH_THRESHOLD:
            card = pick_card_for_tag(user_id, t["tag"])
            if card:
                suggest = {
                    "tag": t["tag"],
                    "tag_label": t["label"],
                    "count": t["count"],
                    "card": card_public(card),
                }
            break
    return {"tags": tags, "total": sum(t["count"] for t in tags), "suggest": suggest}
