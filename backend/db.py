"""数据层：sqlite3 连接、建表、CRUD、连接管理与出参转换。

约定（ARCHITECTURE.md 0/3）：
- 日期时间 ISO8601 `YYYY-MM-DDTHH:MM:SSZ`（UTC），纯日期 `YYYY-MM-DD`；
- 布尔在库里存 INTEGER 0/1，出参统一转 bool；
- 空值用 None（JSON null）。
每个操作开连接、用完关闭；row_factory=sqlite3.Row。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------- 路径 / 时间

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "yaya.db"

DEFAULT_USER_ID = 1


def now_iso() -> str:
    """当前 UTC 时间，ISO8601 秒精度 + Z。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def iso_days_from_now(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


# ---------------------------------------------------------------- 连接管理

def get_conn() -> sqlite3.Connection:
    """打开一个新连接（调用方负责关闭）。data/ 目录运行时创建。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------- 建表

DDL = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    username        TEXT,
    cefr_level      TEXT,
    target_level    TEXT,
    xp              INTEGER DEFAULT 0,
    streak_days     INTEGER DEFAULT 0,
    last_active_date TEXT,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS scenes (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    description TEXT,
    emoji       TEXT,
    color       TEXT,
    cefr_level  TEXT,
    sort_order  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dialogue_turns (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER,
    scene_id      TEXT,
    role          TEXT,
    fr            TEXT,
    cn            TEXT,
    recast_of     TEXT,
    explanation   TEXT,
    is_correction INTEGER DEFAULT 0,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS word_cards (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER,
    word            TEXT,
    meaning         TEXT,
    pos             TEXT,
    example         TEXT,
    pronunciation   TEXT,
    cefr_level      TEXT,
    source_scene_id TEXT,
    created_at      TEXT,
    UNIQUE (user_id, word)
);

CREATE TABLE IF NOT EXISTS review_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id          INTEGER,
    user_id          INTEGER,
    repetitions      INTEGER DEFAULT 0,
    ease_factor      REAL DEFAULT 2.5,
    interval_days    INTEGER DEFAULT 0,
    next_due         TEXT,
    last_reviewed_at TEXT,
    total_reviews    INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_dialogue_scene ON dialogue_turns (scene_id, id);
CREATE INDEX IF NOT EXISTS idx_cards_user ON word_cards (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_review_card ON review_logs (card_id);

-- ===== v2 增量：输入流三表（旧 5 表结构一字不改）=====
CREATE TABLE IF NOT EXISTS input_texts (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    format      TEXT NOT NULL,
    cefr_level  TEXT NOT NULL,
    topic       TEXT NOT NULL,
    body_fr     TEXT NOT NULL,
    body_cn     TEXT NOT NULL,
    audio_url   TEXT,
    audio_text  TEXT,
    word_count  INTEGER NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS input_lines (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text_id    TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    speaker    TEXT,
    fr         TEXT NOT NULL,
    cn         TEXT NOT NULL,
    audio_url  TEXT,
    UNIQUE (text_id, seq)
);

CREATE TABLE IF NOT EXISTS input_words (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    text_id        TEXT NOT NULL,
    line_seq       INTEGER,
    word           TEXT NOT NULL,
    meaning        TEXT NOT NULL,
    pos            TEXT,
    cefr_level     TEXT,
    example        TEXT,
    pronunciation  TEXT,
    word_card_id   INTEGER,
    UNIQUE (text_id, word)
);

CREATE INDEX IF NOT EXISTS idx_input_texts_level ON input_texts (cefr_level, sort_order);
CREATE INDEX IF NOT EXISTS idx_input_lines_text ON input_lines (text_id, seq);
CREATE INDEX IF NOT EXISTS idx_input_words_text ON input_words (text_id);

-- ===== 阶段0 增量：定级/考级尝试表（旧 8 表结构一字不改）=====
CREATE TABLE IF NOT EXISTS attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    kind         TEXT    NOT NULL CHECK (kind IN ('placement', 'exam')),
    score        INTEGER NOT NULL,
    detail_json  TEXT    NOT NULL,
    created_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempts_user_kind ON attempts (user_id, kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_attempts_kind ON attempts (kind);

-- ===== 读音规则学习增量：规则级掌握度（旧表结构一字不改）=====
CREATE TABLE IF NOT EXISTS pronunciation_progress (
    user_id           INTEGER NOT NULL,
    rule_id           TEXT    NOT NULL,
    stage             TEXT    NOT NULL CHECK (stage IN ('seen', 'learned', 'confident')),
    practice_count    INTEGER NOT NULL DEFAULT 0,
    last_practiced_at TEXT,
    self_assessed     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, rule_id)
);

CREATE INDEX IF NOT EXISTS idx_pron_progress_user ON pronunciation_progress (user_id);
CREATE INDEX IF NOT EXISTS idx_pron_progress_user_stage ON pronunciation_progress (user_id, stage);
"""


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(DDL)
        conn.commit()
    finally:
        conn.close()


def is_empty() -> bool:
    conn = get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return row["n"] == 0
    finally:
        conn.close()


# ---------------------------------------------------------------- 出参转换

def row_to_scene(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "emoji": row["emoji"],
        "color": row["color"],
        "cefr_level": row["cefr_level"],
        "sort_order": row["sort_order"],
    }


def row_to_dialogue_turn(row: sqlite3.Row, preset: bool = False) -> dict:
    """preset=True 时为起始对话：按契约 id/recast_of/explanation/created_at 均为 null。"""
    return {
        "id": None if preset else row["id"],
        "role": row["role"],
        "fr": row["fr"],
        "cn": row["cn"],
        "recast_of": None if preset else row["recast_of"],
        "explanation": None if preset else row["explanation"],
        "is_correction": False if preset else bool(row["is_correction"]),
        "created_at": None if preset else row["created_at"],
    }


def row_to_word_card(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "word": row["word"],
        "meaning": row["meaning"],
        "pos": row["pos"],
        "example": row["example"],
        "pronunciation": row["pronunciation"],
        "cefr_level": row["cefr_level"],
        "source_scene_id": row["source_scene_id"],
        "created_at": row["created_at"],
    }


def row_to_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "cefr_level": row["cefr_level"],
        "target_level": row["target_level"],
        "xp": row["xp"],
        "streak_days": row["streak_days"],
        "last_active_date": row["last_active_date"],
        "created_at": row["created_at"],
    }


def row_to_attempt(row: sqlite3.Row) -> dict:
    """attempts 出参：detail_json 保持 JSON 字符串，由调用方 json.loads。"""
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "kind": row["kind"],
        "score": row["score"],
        "detail_json": row["detail_json"],
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------- 场景

def list_scenes() -> list:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM scenes ORDER BY sort_order ASC, id ASC"
        ).fetchall()
        return [row_to_scene(r) for r in rows]
    finally:
        conn.close()


def get_scene(scene_id: str):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM scenes WHERE id = ?", (scene_id,)).fetchone()
        return row_to_scene(row) if row else None
    finally:
        conn.close()


def get_start_dialogue(scene_id: str) -> list:
    """起始对话在 seed 时以 created_at IS NULL 标识，按插入顺序返回。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM dialogue_turns "
            "WHERE scene_id = ? AND created_at IS NULL ORDER BY id ASC",
            (scene_id,),
        ).fetchall()
        return [row_to_dialogue_turn(r, preset=True) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------- 对话轮

def add_dialogue_turn(
    user_id: int,
    scene_id: str,
    role: str,
    fr: str,
    cn: str | None,
    recast_of: str | None = None,
    explanation: str | None = None,
    is_correction: bool = False,
) -> dict:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO dialogue_turns "
            "(user_id, scene_id, role, fr, cn, recast_of, explanation, is_correction, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                scene_id,
                role,
                fr,
                cn,
                recast_of,
                explanation,
                1 if is_correction else 0,
                now_iso(),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM dialogue_turns WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return row_to_dialogue_turn(row)
    finally:
        conn.close()


# ---------------------------------------------------------------- 用户

def ensure_profile_initialized(user_id: int = DEFAULT_USER_ID) -> None:
    """TASK-0040 假值清零迁移（幂等）：users 补 profile_initialized 列；未初始化行清零演示假值。"""
    conn = get_conn()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "profile_initialized" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN profile_initialized INTEGER DEFAULT 0")
            conn.commit()
        row = conn.execute(
            "SELECT profile_initialized FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None or row["profile_initialized"]:
            return
        conn.execute(
            "UPDATE users SET xp = 0, streak_days = 0, last_active_date = NULL, "
            "profile_initialized = 1 WHERE id = ?",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()


def list_dialogue_history(
    user_id: int = DEFAULT_USER_ID,
    scene_id: str | None = None,
    limit: int = 50,
) -> list:
    """TASK-0040：读回真实对话（created_at IS NOT NULL 排除种子预置行），按 id 正序返回。"""
    conn = get_conn()
    try:
        sql = "SELECT * FROM dialogue_turns WHERE user_id = ? AND created_at IS NOT NULL"
        params: list = [user_id]
        if scene_id:
            sql += " AND scene_id = ?"
            params.append(scene_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [row_to_dialogue_turn(r) for r in reversed(rows)]
    finally:
        conn.close()


def clear_dialogue_history(
    user_id: int = DEFAULT_USER_ID,
    scene_id: str | None = None,
) -> int:
    """重置对话：删除真实对话轮（created_at IS NOT NULL），种子预置行保留。返回删除条数。"""
    conn = get_conn()
    try:
        sql = "DELETE FROM dialogue_turns WHERE user_id = ? AND created_at IS NOT NULL"
        params: list = [user_id]
        if scene_id:
            sql += " AND scene_id = ?"
            params.append(scene_id)
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def get_user(user_id: int = DEFAULT_USER_ID):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return row_to_user(row) if row else None
    finally:
        conn.close()


def update_user_activity(user_id: int, xp_delta: int = 0) -> None:
    """每轮 +10 XP（由 app 层按轮数传入），并按 last_active_date 更新连续天数。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT xp, streak_days, last_active_date FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return
        today = datetime.now(timezone.utc).date()
        last_raw = row["last_active_date"]
        try:
            last = datetime.strptime(last_raw, "%Y-%m-%d").date() if last_raw else None
        except ValueError:
            last = None
        if last == today:
            streak = row["streak_days"]
        elif last == today - timedelta(days=1):
            streak = row["streak_days"] + 1
        else:
            streak = 1
        conn.execute(
            "UPDATE users SET xp = ?, streak_days = ?, last_active_date = ? WHERE id = ?",
            (row["xp"] + xp_delta, streak, today.strftime("%Y-%m-%d"), user_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_profile(user_id: int = DEFAULT_USER_ID):
    """UserProfile = 用户字段 + stats 统计对象。"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        profile = row_to_user(row)
        profile.pop("created_at", None)

        now = now_iso()
        week_ago = iso_days_from_now(-7)

        due = conn.execute(
            "SELECT COUNT(*) AS n FROM review_logs WHERE user_id = ? AND next_due <= ?",
            (user_id, now),
        ).fetchone()["n"]
        new_week = conn.execute(
            "SELECT COUNT(*) AS n FROM word_cards WHERE user_id = ? AND created_at >= ?",
            (user_id, week_ago),
        ).fetchone()["n"]
        mastered = conn.execute(
            "SELECT COUNT(*) AS n FROM review_logs WHERE user_id = ? AND repetitions >= 5",
            (user_id,),
        ).fetchone()["n"]
        total_cards = conn.execute(
            "SELECT COUNT(*) AS n FROM word_cards WHERE user_id = ?",
            (user_id,),
        ).fetchone()["n"]
        dialogue_count = conn.execute(
            "SELECT COUNT(*) AS n FROM dialogue_turns "
            "WHERE user_id = ? AND created_at IS NOT NULL",
            (user_id,),
        ).fetchone()["n"]
        agg = conn.execute(
            "SELECT COALESCE(SUM(repetitions),0) AS reps, "
            "COALESCE(SUM(total_reviews),0) AS total "
            "FROM review_logs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        total = agg["total"]
        accuracy = round(agg["reps"] / total, 2) if total else 0.0

        profile["stats"] = {
            "due_cards_count": due,
            "new_words_week": new_week,
            "mastered_count": mastered,
            "accuracy": accuracy,
            "total_cards": total_cards,
            "dialogue_count": dialogue_count,
            "review_count": total,
        }
        return profile
    finally:
        conn.close()


# ---------------------------------------------------------------- 生词卡

def card_exists(user_id: int, word: str) -> bool:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM word_cards WHERE user_id = ? AND word = ?", (user_id, word)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def create_card(
    user_id: int,
    word: str,
    meaning: str | None,
    pos: str | None,
    example: str | None = None,
    pronunciation: str | None = None,
    cefr_level: str | None = None,
    source_scene_id: str | None = None,
):
    """建卡（查重）+ 同步插入初始 review_logs。已存在则返回已有卡片 dict。"""
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT * FROM word_cards WHERE user_id = ? AND word = ?", (user_id, word)
        ).fetchone()
        if existing:
            return row_to_word_card(existing)

        created = now_iso()
        cur = conn.execute(
            "INSERT INTO word_cards "
            "(user_id, word, meaning, pos, example, pronunciation, cefr_level, source_scene_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                word,
                meaning,
                pos,
                example,
                pronunciation,
                cefr_level,
                source_scene_id,
                created,
            ),
        )
        card_id = cur.lastrowid
        # 初始复习记录：repetitions=0, ease_factor=2.5, interval_days=0, next_due=当前时间
        conn.execute(
            "INSERT INTO review_logs "
            "(card_id, user_id, repetitions, ease_factor, interval_days, next_due, "
            "last_reviewed_at, total_reviews) "
            "VALUES (?, ?, 0, 2.5, 0, ?, NULL, 0)",
            (card_id, user_id, created),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM word_cards WHERE id = ?", (card_id,)).fetchone()
        return row_to_word_card(row)
    finally:
        conn.close()


def list_cards(scene_id: str | None = None, user_id: int = DEFAULT_USER_ID) -> list:
    conn = get_conn()
    try:
        if scene_id:
            rows = conn.execute(
                "SELECT * FROM word_cards WHERE user_id = ? AND source_scene_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (user_id, scene_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM word_cards WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                (user_id,),
            ).fetchall()
        return [row_to_word_card(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------- 复习

def get_review_state(card_id: int, user_id: int = DEFAULT_USER_ID):
    """取该卡当前的 review_logs 状态；卡片不存在返回 None。"""
    conn = get_conn()
    try:
        card = conn.execute(
            "SELECT 1 FROM word_cards WHERE id = ?", (card_id,)
        ).fetchone()
        if card is None:
            return None
        row = conn.execute(
            "SELECT * FROM review_logs WHERE card_id = ? ORDER BY id DESC LIMIT 1",
            (card_id,),
        ).fetchone()
        if row is None:
            # 理论上建卡时必插；兜底防御，返回初始状态
            return {
                "repetitions": 0,
                "ease_factor": 2.5,
                "interval_days": 0,
                "next_due": now_iso(),
                "total_reviews": 0,
            }
        return {
            "repetitions": row["repetitions"],
            "ease_factor": row["ease_factor"],
            "interval_days": row["interval_days"],
            "next_due": row["next_due"],
            "total_reviews": row["total_reviews"],
        }
    finally:
        conn.close()


def update_review(
    card_id: int,
    new_state: dict,
    next_due: str,
    user_id: int = DEFAULT_USER_ID,
) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE review_logs SET repetitions = ?, ease_factor = ?, interval_days = ?, "
            "next_due = ?, last_reviewed_at = ?, total_reviews = total_reviews + 1 "
            "WHERE card_id = ?",
            (
                new_state["repetitions"],
                new_state["ease_factor"],
                new_state["interval_days"],
                next_due,
                now_iso(),
                card_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ================================================================ v2 输入流数据访问
# 三张新表 + 复用 word_cards / create_card；所有出参严格对齐 §5.2 Schema。

CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]
INPUT_LEVELS = ("A2", "B1", "B2")


def _cefr_index(level) -> int:
    return CEFR_ORDER.index(level) if level in CEFR_ORDER else 0


def _row_to_input_text_summary(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "format": row["format"],
        "cefr_level": row["cefr_level"],
        "topic": row["topic"],
        "word_count": row["word_count"],
        "audio_url": row["audio_url"],
        "sort_order": row["sort_order"],
    }


def _row_to_input_text(row: sqlite3.Row) -> dict:
    """input_texts 全部 13 字段。"""
    return {
        "id": row["id"],
        "title": row["title"],
        "format": row["format"],
        "cefr_level": row["cefr_level"],
        "topic": row["topic"],
        "body_fr": row["body_fr"],
        "body_cn": row["body_cn"],
        "audio_url": row["audio_url"],
        "audio_text": row["audio_text"],
        "word_count": row["word_count"],
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_input_line(row: sqlite3.Row) -> dict:
    return {
        "seq": row["seq"],
        "speaker": row["speaker"],
        "fr": row["fr"],
        "cn": row["cn"],
        "audio_url": row["audio_url"],
    }


def _row_to_input_word(row: sqlite3.Row) -> dict:
    return {
        "word": row["word"],
        "meaning": row["meaning"],
        "pos": row["pos"],
        "cefr_level": row["cefr_level"],
        "example": row["example"],
        "pronunciation": row["pronunciation"],
        "line_seq": row["line_seq"],
        "word_card_id": row["word_card_id"],
    }


_WORD_ORDER_SQL = "ORDER BY (line_seq IS NULL) ASC, line_seq ASC, word ASC"


def list_input_levels() -> list:
    """LevelInfo[]，只返回有语料的 A2/B1/B2，按 CEFR 顺序。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT cefr_level, COUNT(*) AS n FROM input_texts GROUP BY cefr_level"
        ).fetchall()
        counts = {r["cefr_level"]: r["n"] for r in rows}
        return [
            {"level": level, "count": counts[level]}
            for level in CEFR_ORDER
            if level in INPUT_LEVELS and counts.get(level, 0) > 0
        ]
    finally:
        conn.close()


def list_input_texts(level: str | None = None, limit: int = 20, offset: int = 0) -> dict:
    """TextListResult：CEFR 顺序 + sort_order 升序，再分页。"""
    conn = get_conn()
    try:
        if level:
            rows = conn.execute(
                "SELECT * FROM input_texts WHERE cefr_level = ?", (level,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM input_texts").fetchall()
        rows = sorted(
            rows,
            key=lambda r: (_cefr_index(r["cefr_level"]), r["sort_order"], r["id"]),
        )
        return {
            "items": [
                _row_to_input_text_summary(r) for r in rows[offset : offset + limit]
            ],
            "total": len(rows),
            "level": level,
        }
    finally:
        conn.close()


def get_input_text_detail(text_id: str) -> dict | None:
    """InputTextDetail（含 lines / words）；不存在返回 None。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM input_texts WHERE id = ?", (text_id,)
        ).fetchone()
        if row is None:
            return None
        detail = _row_to_input_text(row)
        detail["lines"] = [
            _row_to_input_line(r)
            for r in conn.execute(
                "SELECT * FROM input_lines WHERE text_id = ? ORDER BY seq ASC",
                (text_id,),
            ).fetchall()
        ]
        detail["words"] = [
            _row_to_input_word(r)
            for r in conn.execute(
                f"SELECT * FROM input_words WHERE text_id = ? {_WORD_ORDER_SQL}",
                (text_id,),
            ).fetchall()
        ]
        return detail
    finally:
        conn.close()


def get_input_text_row(text_id: str) -> dict | None:
    """轻量取 input_texts 单行的全部字段，不存在返回 None（供推荐打分用）。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM input_texts WHERE id = ?", (text_id,)
        ).fetchone()
        return _row_to_input_text(row) if row else None
    finally:
        conn.close()


def get_all_input_texts() -> list:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM input_texts").fetchall()
        return [_row_to_input_text(r) for r in rows]
    finally:
        conn.close()


def get_input_words(text_id: str) -> list:
    conn = get_conn()
    try:
        return [
            _row_to_input_word(r)
            for r in conn.execute(
                f"SELECT * FROM input_words WHERE text_id = ? {_WORD_ORDER_SQL}",
                (text_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def get_mastered_words(user_id: int = DEFAULT_USER_ID) -> set:
    """掌握度口径：review_logs.repetitions >= 5 的 word 集合（§4.3 / §6）。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT c.word FROM word_cards c "
            "JOIN review_logs r ON r.card_id = c.id "
            "WHERE c.user_id = ? AND r.repetitions >= 5",
            (user_id,),
        ).fetchall()
        return {r["word"] for r in rows}
    finally:
        conn.close()


def collect_input_words(
    text_id: str, words: list | None = None, user_id: int = DEFAULT_USER_ID
) -> dict | None:
    """收词入库：复用 create_card（含查重 + 初始 review_logs），回填 word_card_id。

    words 为 None / 空列表 → 收该文本全部生词；否则只收存在于 input_words 的词。
    文本不存在返回 None（由 API 层转 404）。幂等：重复调用不重复建卡。
    """
    # 第一段：单连接读取目标生词，随即关闭，避免与 create_card 的独立连接争抢写锁。
    conn = get_conn()
    try:
        if (
            conn.execute(
                "SELECT 1 FROM input_texts WHERE id = ?", (text_id,)
            ).fetchone()
            is None
        ):
            return None
        rows = [
            dict(r)
            for r in conn.execute(
                f"SELECT * FROM input_words WHERE text_id = ? {_WORD_ORDER_SQL}",
                (text_id,),
            ).fetchall()
        ]
    finally:
        conn.close()

    if words:
        wanted = set(words)
        rows = [r for r in rows if r["word"] in wanted]

    collected: list = []
    already_existed: list = []
    skipped: list = []
    backfill: list = []
    for r in rows:
        word, meaning = r.get("word"), r.get("meaning")
        if not (
            isinstance(word, str)
            and word.strip()
            and isinstance(meaning, str)
            and meaning.strip()
        ):
            skipped.append(word if isinstance(word, str) else str(word))
            continue
        existed = card_exists(user_id, word)
        card = create_card(
            user_id=user_id,
            word=word,
            meaning=meaning,
            pos=r.get("pos"),
            example=r.get("example"),
            pronunciation=r.get("pronunciation"),
            cefr_level=r.get("cefr_level"),
            source_scene_id=None,  # 输入流来源语义存 input_words.word_card_id，不污染场景字段
        )
        collected.append(card)
        if existed:
            already_existed.append(word)
        backfill.append((card["id"], r["id"]))

    if backfill:
        conn = get_conn()
        try:
            conn.executemany(
                "UPDATE input_words SET word_card_id = ? WHERE id = ?", backfill
            )
            conn.commit()
        finally:
            conn.close()

    return {
        "text_id": text_id,
        "collected": collected,
        "already_existed": already_existed,
        "skipped": skipped,
    }


# ================================================================ 阶段0 增量：定级尝试
# attempts 仅存原始记录，本阶段只写 kind='placement'；kind='exam' 为波二预留。

def add_attempt(user_id: int, kind: str, score: int, detail: dict) -> dict:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO attempts (user_id, kind, score, detail_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, kind, score, json.dumps(detail, ensure_ascii=False), now_iso()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM attempts WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return row_to_attempt(row)
    finally:
        conn.close()


def get_latest_attempt(user_id: int, kind: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM attempts WHERE user_id = ? AND kind = ? ORDER BY id DESC LIMIT 1",
            (user_id, kind),
        ).fetchone()
        return row_to_attempt(row) if row else None
    finally:
        conn.close()


def count_attempts(user_id: int, kind: str) -> int:
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM attempts WHERE user_id = ? AND kind = ?",
            (user_id, kind),
        ).fetchone()["n"]
    finally:
        conn.close()


def set_user_cefr_level(user_id: int, level: str) -> None:
    """只更新 cefr_level；target_level / xp / streak_days 一律不动。"""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE users SET cefr_level = ? WHERE id = ?", (level, user_id)
        )
        conn.commit()
    finally:
        conn.close()


# ================================================================ 读音规则学习增量：规则级掌握度
# 契约 PRONUNCIATION_CONTRACT.md v1.0 §2.1 / §3.3 / §3.4；所有 SQL 显式带 user_id。

def _row_to_progress_item(row: sqlite3.Row) -> dict:
    """ProgressItem 出参：self_assessed 由库内 0/1 转 bool。"""
    return {
        "rule_id": row["rule_id"],
        "stage": row["stage"],
        "practice_count": row["practice_count"],
        "last_practiced_at": row["last_practiced_at"],
        "self_assessed": bool(row["self_assessed"]),
    }


def get_progress(user_id: int = DEFAULT_USER_ID) -> dict:
    """读取当前用户全部进度：统计 + 明细（total_rules 由 app 层按规则缓存补）。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM pronunciation_progress WHERE user_id = ? ORDER BY rule_id ASC",
            (user_id,),
        ).fetchall()
        counts = {"seen": 0, "learned": 0, "confident": 0}
        for row in rows:
            counts[row["stage"]] = counts.get(row["stage"], 0) + 1
        return {
            "user_id": user_id,
            "seen_count": counts["seen"],
            "learned_count": counts["learned"],
            "confident_count": counts["confident"],
            "learned_total": counts["learned"] + counts["confident"],
            "items": [_row_to_progress_item(row) for row in rows],
        }
    finally:
        conn.close()


def upsert_progress(
    user_id: int,
    rule_id: str,
    stage: str | None = None,
    self_assessed: int | None = None,
) -> dict:
    """幂等 upsert 某规则的掌握状态，返回更新后的 ProgressItem。

    ★裁决④：practice_count 服务端 +1 累加（新记录从 1 起），不接受客户端目标值；
    self_assessed 只增不减（已有 1 传 0 保留 1，None 表示缺省保留旧值）；
    last_practiced_at 每次由服务端 now_iso() 写入。
    """
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM pronunciation_progress WHERE user_id = ? AND rule_id = ?",
            (user_id, rule_id),
        ).fetchone()
        ts = now_iso()
        if row is None:
            final_stage = "seen" if stage is None else stage
            final_self = 1 if self_assessed else 0
            conn.execute(
                "INSERT INTO pronunciation_progress "
                "(user_id, rule_id, stage, practice_count, last_practiced_at, self_assessed) "
                "VALUES (?, ?, ?, 1, ?, ?)",
                (user_id, rule_id, final_stage, ts, final_self),
            )
        else:
            final_stage = row["stage"] if stage is None else stage
            if self_assessed is None:
                final_self = row["self_assessed"]
            else:
                final_self = 1 if (row["self_assessed"] or self_assessed) else 0
            conn.execute(
                "UPDATE pronunciation_progress SET stage = ?, "
                "practice_count = practice_count + 1, last_practiced_at = ?, self_assessed = ? "
                "WHERE user_id = ? AND rule_id = ?",
                (final_stage, ts, final_self, user_id, rule_id),
            )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM pronunciation_progress WHERE user_id = ? AND rule_id = ?",
            (user_id, rule_id),
        ).fetchone()
        return _row_to_progress_item(row)
    finally:
        conn.close()
