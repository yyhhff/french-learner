"""TASK-0071 v3.1 听力强化路由：分级听力 + 精听听写填空 + 真实语速变体 + 画像挂接。

素材全部来自 v2.3 批量线既有资产（input_texts / input_lines 只读，不回填 audio_url 字段，
沿用 /api/content/audio/{text_id}/{seq} 的 seq 寻址约定）：
- 标准音频 audio/<text_id>/<seq>.mp3（v2.3 批量线产出）；
- 变体音频 <seq>_v1.mp3（男声 HenriNeural 原文）/ <seq>_v2.mp3（Denise + 缩略形 +10% 语速），
  由 content_pipeline 的 audio-variants 批量生成（断点续跑），未就绪时端点如实返回 False。

诚实边界：详情端点不下发整句法文原文（精听答案不下发，挖空词答案留在服务端判分），
提交答案后才在响应中回显原句与缩略形对照。

车道边界（docs/MASTER_PLAN.md 规则 3）：
- listening_logs 表在本模块 init_tables() 内自建，不动 db.py 公共区；
- 画像只写 skill_events 流水（skill='listening'，source 复用 'input'），懒计算进 skill_profile；
- ROADMAP_DEFS 不在此点亮（集成会话负责）；XP 记账归 v3.0 gamify 车道。
"""
from __future__ import annotations

import random
import re
import time
import unicodedata
from pathlib import Path

from fastapi import APIRouter, Request

import db
from common import ApiError, _record_skill_events, json_body, logger, ok

router = APIRouter()

# ---------------------------------------------------------------- 纯函数：分词 / 挖空 / 判分

# 分词后剥掉的边缘标点（撇号不在列：l'homme / qu'un 是词内部分）
_SPLIT_STRIP = "«».,!?;:\"“”…()—––[]"

# 听写挖空跳过的功能词（虚词没有听写训练价值）
_STOPWORDS = {
    "le", "la", "les", "un", "une", "de", "du", "des", "et", "ou", "où",
    "à", "au", "aux", "en", "y", "je", "tu", "il", "elle", "on", "nous",
    "vous", "ils", "elles", "me", "te", "se", "ne", "pas", "que", "qui",
    "quoi", "ce", "cet", "cette", "ces", "son", "sa", "ses", "est", "sont",
    "mais", "donc", "car", "si", "comme", "quand", "plus", "très", "bien",
}

# 每等级挖空词数（A1 最轻，B1/B2 最重）
_BLANK_COUNT = {"A1": 1, "A2": 2}


def _split_words(fr: str) -> list[str]:
    """整句按空白切词并剥边缘标点（保留词内撇号/连字符）。"""
    return [t for t in (w.strip(_SPLIT_STRIP) for w in str(fr).split()) if t]


def pick_blank_indices(words: list[str], level: str, salt: str) -> list[int]:
    """按等级选听写挖空词位（确定性：同 salt 结果恒定，可复算判分）。

    A1=1 / A2=2 / B1·B2=3 个；优先实词（非虚词、长度≥3）；行词数 <3 不出填空。
    """
    if len(words) < 3:
        return []
    want = _BLANK_COUNT.get(level, 3)
    pool = [i for i, w in enumerate(words) if len(w) >= 3 and w.lower() not in _STOPWORDS]
    if len(pool) < want:
        pool = [i for i, w in enumerate(words) if len(w) >= 3] or list(range(len(words)))
    rng = random.Random(salt)
    return sorted(rng.sample(pool, min(want, len(pool))))


def _normalize_answer(s: str) -> str:
    """听写判分归一：去重音符号、小写、标点转空格、压缩空白。

    宽松口径（入门友好）：é/è/ê 均算对；大小写与标点不计对错。
    """
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _audio_flags(text_id: str, seqs: list[int]) -> dict[str, int]:
    """统计一篇各句音频就绪数（标准 / v1 男声 / v2 缩略形真实语速）。"""
    from content_pipeline.paths import AUDIO_DIR  # 与 content_review.py 同法：运行时延迟导入

    d = AUDIO_DIR / text_id
    counts = {"audio_ready": 0, "v1_ready": 0, "v2_ready": 0}
    for seq in seqs:
        if (d / f"{seq}.mp3").is_file():
            counts["audio_ready"] += 1
        if (d / f"{seq}_v1.mp3").is_file():
            counts["v1_ready"] += 1
        if (d / f"{seq}_v2.mp3").is_file():
            counts["v2_ready"] += 1
    return counts


def _level_rows(conn, level: str) -> list:
    """取某等级全部语料（含句 seq 列表），按 cefr_level、sort_order、id 排序。"""
    texts = conn.execute(
        "SELECT id, title, topic, cefr_level, format FROM input_texts "
        "WHERE (? = '' OR cefr_level = ?) ORDER BY cefr_level, sort_order, id",
        (level, level),
    ).fetchall()
    out = []
    for t in texts:
        seqs = [r["seq"] for r in conn.execute(
            "SELECT seq FROM input_lines WHERE text_id = ? ORDER BY seq", (t["id"],)
        ).fetchall()]
        out.append({**dict(t), "seqs": seqs})
    return out


# ---------------------------------------------------------------- 表初始化（模块自建，不动 db.py 公共区）

def init_tables() -> None:
    """幂等建 listening_logs（精听记录）；失败不阻断启动（其余端点正常）。"""
    try:
        conn = db.get_conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS listening_logs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL DEFAULT 1,
                    text_id    TEXT NOT NULL,
                    seq        INTEGER NOT NULL,
                    mode       TEXT NOT NULL DEFAULT 'dictation',
                    typed      TEXT,
                    correct    INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_listening_logs_user
                    ON listening_logs (user_id, text_id, seq);
                """
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — 画像/记录是增益功能，不阻断启动
        logger.warning("listening_logs 建表异常（听力记录将不可用）：%s", exc)


# ---------------------------------------------------------------- 端点

@router.get("/api/listen/levels")
async def listen_levels():
    """四档听力素材总览：篇数 / 句数 / 音频就绪（标准与两类变体分开计数）。"""
    conn = db.get_conn()
    try:
        rows = _level_rows(conn, "")
    finally:
        conn.close()
    by_level: dict[str, dict] = {}
    for t in rows:
        lv = t["cefr_level"]
        slot = by_level.setdefault(lv, {"level": lv, "texts": 0, "lines": 0,
                                        "audio_ready": 0, "v1_ready": 0, "v2_ready": 0})
        slot["texts"] += 1
        slot["lines"] += len(t["seqs"])
        flags = _audio_flags(t["id"], t["seqs"])
        for k in ("audio_ready", "v1_ready", "v2_ready"):
            slot[k] += flags[k]
    return ok({"levels": sorted(by_level.values(), key=lambda x: x["level"])})


@router.get("/api/listen/texts")
async def listen_texts(level: str = ""):
    """某等级听力素材清单（level 缺省 = 全部）。"""
    level = (level or "").strip().upper()
    if level and level not in {"A1", "A2", "B1", "B2"}:
        raise ApiError(40001, 400, "level 须为 A1/A2/B1/B2 或留空")
    conn = db.get_conn()
    try:
        rows = _level_rows(conn, level)
    finally:
        conn.close()
    texts = []
    for t in rows:
        flags = _audio_flags(t["id"], t["seqs"])
        texts.append({
            "id": t["id"], "title": t["title"], "topic": t["topic"],
            "cefr_level": t["cefr_level"], "format": t["format"],
            "lines": len(t["seqs"]), **flags,
        })
    return ok({"level": level, "texts": texts})


@router.get("/api/listen/texts/{text_id}")
async def listen_text_detail(text_id: str):
    """篇详情：逐句中文提示 + 挖空版词序列（答案词位以 null 下发，原句不下发）。

    words 中挖空位为 null，blanks 给出 {idx, letters}（词长提示）；
    判分所需答案只留在服务端（answer 端点按同 salt 复算）。
    """
    conn = db.get_conn()
    try:
        t = conn.execute(
            "SELECT id, title, topic, cefr_level, format FROM input_texts WHERE id = ?",
            (text_id,),
        ).fetchone()
        if not t:
            raise ApiError(40401, 404, "听力素材不存在")
        lines = conn.execute(
            "SELECT seq, fr, cn, speaker FROM input_lines WHERE text_id = ? ORDER BY seq",
            (text_id,),
        ).fetchall()
    finally:
        conn.close()
    today = db.today_str()
    out_lines = []
    for ln in lines:
        words = _split_words(ln["fr"])
        blanks = pick_blank_indices(words, t["cefr_level"], f"{text_id}:{ln['seq']}:{today}")
        masked = [None if i in blanks else w for i, w in enumerate(words)]
        out_lines.append({
            "seq": ln["seq"], "cn": ln["cn"], "speaker": ln["speaker"],
            "words": masked,
            "blanks": [{"idx": i, "letters": len(words[i])} for i in blanks],
            **_audio_flags(text_id, [ln["seq"]]),
        })
    return ok({**dict(t), "lines": out_lines})


@router.post("/api/listen/answer")
async def listen_answer(request: Request):
    """精听单句提交：服务端复算挖空位并判分，落 listening_logs 后回显原句对照。"""
    body = await json_body(request)
    text_id = str(body.get("text_id") or "").strip()
    typed = body.get("typed")
    try:
        seq = int(body.get("seq"))
    except (TypeError, ValueError):
        raise ApiError(40001, 400, "seq 无效")
    if not text_id or not isinstance(typed, list):
        raise ApiError(40001, 400, "缺少 text_id 或 typed")
    conn = db.get_conn()
    try:
        t = conn.execute(
            "SELECT cefr_level FROM input_texts WHERE id = ?", (text_id,)
        ).fetchone()
        ln = conn.execute(
            "SELECT fr, cn FROM input_lines WHERE text_id = ? AND seq = ?", (text_id, seq)
        ).fetchone()
    finally:
        conn.close()
    if not t or not ln:
        raise ApiError(40401, 404, "听力素材或句不存在")
    words = _split_words(ln["fr"])
    blanks = pick_blank_indices(words, t["cefr_level"], f"{text_id}:{seq}:{db.today_str()}")
    if not blanks:
        raise ApiError(40002, 400, "本句过短，无可挖空词")
    if len(typed) != len(blanks) or not all(isinstance(x, str) for x in typed):
        raise ApiError(40001, 400, "typed 数量与挖空数不符")
    answers = [words[i] for i in blanks]
    per_word = [_normalize_answer(a) == _normalize_answer(b) and bool(_normalize_answer(a))
                for a, b in zip(typed, answers)]
    correct = 1 if all(per_word) else 0
    try:
        conn = db.get_conn()
        try:
            conn.execute(
                "INSERT INTO listening_logs (user_id, text_id, seq, mode, typed, correct, created_at) "
                "VALUES (?, ?, ?, 'dictation', ?, ?, ?)",
                (db.DEFAULT_USER_ID, text_id, seq, "|".join(typed), correct, db.now_iso()),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — 记录失败不阻塞判分反馈
        logger.warning("listening_logs 写入失败：%s", exc)
    from reductions import reduce_sentence
    return ok({
        "correct": bool(correct),
        "per_word": per_word,
        "answers": answers,
        "fr": ln["fr"],
        "fr_reduced": reduce_sentence(ln["fr"]),
        "cn": ln["cn"],
    })


@router.post("/api/listen/finish")
async def listen_finish(request: Request):
    """精听整篇收口：按 listening_logs 汇总正确率，写一条 listening 画像事件。"""
    body = await json_body(request)
    text_id = str(body.get("text_id") or "").strip()
    if not text_id:
        raise ApiError(40001, 400, "缺少 text_id")
    conn = db.get_conn()
    try:
        t = conn.execute(
            "SELECT title, cefr_level FROM input_texts WHERE id = ?", (text_id,)
        ).fetchone()
        if not t:
            raise ApiError(40401, 404, "听力素材不存在")
        lines_total = conn.execute(
            "SELECT COUNT(*) AS n FROM input_lines WHERE text_id = ?", (text_id,)
        ).fetchone()["n"]
        attempted = conn.execute(
            "SELECT COUNT(DISTINCT seq) AS n FROM listening_logs "
            "WHERE user_id = ? AND text_id = ?",
            (db.DEFAULT_USER_ID, text_id),
        ).fetchone()["n"]
        correct_seqs = conn.execute(
            "SELECT COUNT(DISTINCT seq) AS n FROM listening_logs "
            "WHERE user_id = ? AND text_id = ? AND correct = 1",
            (db.DEFAULT_USER_ID, text_id),
        ).fetchone()["n"]
    finally:
        conn.close()
    if attempted == 0:
        raise ApiError(40002, 400, "本篇还没有精听记录")
    score = round(correct_seqs / lines_total * 100) if lines_total else 0
    _record_skill_events([("listening", score, "input", text_id)])
    return ok({
        "title": t["title"], "cefr_level": t["cefr_level"],
        "lines_total": lines_total, "attempted": attempted,
        "correct_seqs": correct_seqs, "score": score,
    })


@router.get("/api/listen/profile")
async def listen_profile():
    """听力画像聚合：累计答题 / 正确率 / 练过篇数 / 近 7 天 / 画像维度快照。"""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(correct), 0) AS correct "
            "FROM listening_logs WHERE user_id = ?",
            (db.DEFAULT_USER_ID,),
        ).fetchone()
        texts_practiced = conn.execute(
            "SELECT COUNT(DISTINCT text_id) AS n FROM listening_logs WHERE user_id = ?",
            (db.DEFAULT_USER_ID,),
        ).fetchone()["n"]
        week = conn.execute(
            "SELECT COUNT(*) AS n FROM listening_logs WHERE user_id = ? AND created_at >= ?",
            (db.DEFAULT_USER_ID, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 7 * 86400))),
        ).fetchone()["n"]
        skill = conn.execute(
            "SELECT score, trend, level_estimate, updated_at FROM skill_profile "
            "WHERE user_id = ? AND skill = 'listening'",
            (db.DEFAULT_USER_ID,),
        ).fetchone()
    finally:
        conn.close()
    return ok({
        "answers_total": row["total"],
        "answers_correct": row["correct"],
        "accuracy": round(row["correct"] / row["total"] * 100) if row["total"] else None,
        "texts_practiced": texts_practiced,
        "answers_7d": week,
        "skill": dict(skill) if skill else None,
    })
