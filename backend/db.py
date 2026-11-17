"""数据层：sqlite3 连接、建表、CRUD、连接管理与出参转换。

约定（ARCHITECTURE.md 0/3）：
- 日期时间 ISO8601 `YYYY-MM-DDTHH:MM:SSZ`（UTC），纯日期 `YYYY-MM-DD`；
- 布尔在库里存 INTEGER 0/1，出参统一转 bool；
- 空值用 None（JSON null）。
每个操作开连接、用完关闭；row_factory=sqlite3.Row。
"""
from __future__ import annotations

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
            "SELECT COUNT(*) AS n FROM review_logs WHERE next_due <= ?", (now,)
        ).fetchone()["n"]
        new_week = conn.execute(
            "SELECT COUNT(*) AS n FROM word_cards WHERE user_id = ? AND created_at >= ?",
            (user_id, week_ago),
        ).fetchone()["n"]
        mastered = conn.execute(
            "SELECT COUNT(*) AS n FROM review_logs WHERE user_id = ? AND repetitions >= 5",
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
