"""v3.0 每天十五分钟：XP 记账 + 等级曲线 + 今日任务聚合（TASK-0070）。

设计要点（方案已确认，2026-11-21）：
- 复用 TASK-0060 存量：users.xp 累积 + streak（update_user_activity）——本模块只补
  XP 来源明细（xp_events 表，本模块 init 建，并行红线不动 db.py 公共区）与等级曲线。
- award() 由各车道挂接点后置调用（chat/review/reading/跟读），内部全程 try/except，
  绝不阻塞主流程；daily_tasks 无状态表——三件事实时从既有表聚合（比方案更简，少一张表）。
- XP 规则：复习 2/卡 · 首读 15/篇 · 对话 3/轮（日封顶 30）· 跟读 5/次（日封顶 20）。
- 断签不惩罚：streak 只断链不归零，文案禁负面词（沿用 0060 口径）。
"""
import sqlite3
from datetime import datetime, timedelta, timezone

import db

# ---------------------------------------------------------------- 常量与曲线

# 各来源日封顶：防"睡前狂刷"，超过后当日不再发放（streak 仍照常更新）
DAILY_CAPS = {"chat": 30, "shadow": 20, "review": 60, "read": 60}

# 等级曲线（前缓后陡）：达到 Lv N 的累计门槛 = 30*N*(N-1)（Lv1=0 起，Lv2=60, Lv3=180, Lv4=360…）
LEVEL_NAMES = {1: "初识", 2: "熟悉", 3: "默契", 4: "老友", 5: "挚友", 6: "灵魂伙伴"}


def xp_total_for_level(level: int) -> int:
    """达到 Lv level 的累计 XP 门槛（Lv1 从 0 起）。"""
    if level <= 1:
        return 0
    return 30 * level * (level - 1)


def level_for_xp(xp: int) -> dict:
    """XP → {level, name, cur, need}。cur/need = 本级段内进度。纯函数，可单测。"""
    xp = max(0, int(xp))
    level = 1
    while xp_total_for_level(level + 1) <= xp and level < 50:
        level += 1
    base = xp_total_for_level(level)
    seg = xp_total_for_level(level + 1) - base
    cur = xp - base
    return {
        "level": level,
        "name": LEVEL_NAMES.get(level, f"Lv{level}"),
        "cur": cur,
        "need": seg,
    }


# ---------------------------------------------------------------- 表

def init_tables() -> None:
    """xp_events 明细表（并行红线：不动 db.py 公共区，独立 CREATE IF NOT EXISTS）。"""
    conn = db.get_conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS xp_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                day        TEXT    NOT NULL,
                source     TEXT    NOT NULL,
                amount     INTEGER NOT NULL,
                detail     TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_xp_user_day ON xp_events (user_id, day);
            """
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- 记账

def award(source: str, amount: int, detail: str | None = None,
          user_id: int = db.DEFAULT_USER_ID) -> int:
    """发放 XP：受日封顶约束，写入明细并复用 update_user_activity 更新总量与 streak。

    任何异常静默吞掉（返回 0）——奖励失败绝不能弄坏学习主流程。返回实际发放值。
    """
    try:
        amount = max(0, int(amount))
        if amount <= 0:
            return 0
        conn = db.get_conn()
        try:
            day = _today()
            granted = amount
            cap = DAILY_CAPS.get(source)
            if cap is not None:
                row = conn.execute(
                    "SELECT COALESCE(SUM(amount),0) AS s FROM xp_events "
                    "WHERE user_id = ? AND day = ? AND source = ?",
                    (user_id, day, source),
                ).fetchone()
                granted = max(0, min(amount, cap - row["s"]))
            if granted > 0:
                conn.execute(
                    "INSERT INTO xp_events (user_id, day, source, amount, detail, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (user_id, day, source, granted, detail, db.now_iso()),
                )
                conn.commit()
        finally:
            conn.close()
        # streak/X 总量更新复用 0060 存量函数（哪怕 granted=0 也要触达，保持"今日已活跃"）
        db.update_user_activity(user_id, xp_delta=granted)
        return granted
    except Exception:  # noqa: BLE001 - 奖励路径绝不阻塞学习主流程
        return 0


def today_xp(user_id: int = db.DEFAULT_USER_ID) -> dict:
    """今日 XP 汇总：总量 + 各来源明细。失败降级为全零。"""
    empty = {"today": 0, "sources": {}, "total": 0}
    try:
        conn = db.get_conn()
        try:
            day = _today()
            row = conn.execute(
                "SELECT COALESCE(SUM(amount),0) AS s FROM xp_events "
                "WHERE user_id = ? AND day = ?",
                (user_id, day),
            ).fetchone()
            rows = conn.execute(
                "SELECT source, SUM(amount) AS s FROM xp_events "
                "WHERE user_id = ? AND day = ? GROUP BY source",
                (user_id, day),
            ).fetchall()
            total_row = conn.execute(
                "SELECT xp FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return {
                "today": row["s"],
                "sources": {r["source"]: r["s"] for r in rows},
                "total": (total_row["xp"] if total_row else 0),
            }
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return empty


# ---------------------------------------------------------------- 今日任务聚合

def today_summary(user_id: int = db.DEFAULT_USER_ID) -> dict:
    """GET /api/today 数据体：三件事 + XP/等级 + streak + 呀呀状态。

    全部实时聚合既有表（reading_logs / review_logs / dialogue_turns / users），
    无状态任务表；失败逐块降级，永不 500。
    """
    conn = db.get_conn()
    try:
        day_start = _today() + "T00:00:00Z"

        # ① 复习：目标 = min(10, 到期数)（口径复用 db.count_due_reviews，与复习入口一致）；
        # 没有到期词是好事，直接视为完成
        due = db.count_due_reviews(user_id)
        reviewed_today = conn.execute(
            "SELECT COUNT(*) AS n FROM review_logs "
            "WHERE user_id = ? AND last_reviewed_at >= ?",
            (user_id, day_start),
        ).fetchone()["n"]
        review_target = min(10, due) if due > 0 else 0
        tasks = [{
            "key": "review",
            "label": "复习 10 个词" if review_target >= 10 else
                     (f"复习 {review_target} 个词" if review_target > 0 else "今天没有到期词"),
            "done": review_target == 0 or reviewed_today >= review_target,
            "count": reviewed_today,
            "target": review_target,
        }]

        # ② 阅读：今日完成 1 篇（首读才算，幂等 reading_logs 天然支持）
        read_today = conn.execute(
            "SELECT COUNT(*) AS n FROM reading_logs "
            "WHERE user_id = ? AND created_at >= ?",
            (user_id, day_start),
        ).fetchone()["n"]
        tasks.append({
            "key": "read", "label": "读 1 篇短文",
            "done": read_today >= 1, "count": min(read_today, 1), "target": 1,
        })

        # ③ 对话：A1 新手 3 轮起步，其余 5 轮（按 user 角色行计数）
        urow = conn.execute(
            "SELECT cefr_level FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        user_level = (urow["cefr_level"] if urow else "A2") or "A2"
        chat_target = 3 if user_level == "A1" else 5
        chat_today = conn.execute(
            "SELECT COUNT(*) AS n FROM dialogue_turns "
            "WHERE user_id = ? AND role = 'user' AND created_at >= ?",
            (user_id, day_start),
        ).fetchone()["n"]
        tasks.append({
            "key": "chat",
            "label": f"和呀呀聊 {chat_target} 轮",
            "done": chat_today >= chat_target,
            "count": min(chat_today, chat_target), "target": chat_target,
        })

        # XP / 等级
        xp = today_xp(user_id)
        lv = level_for_xp(xp.get("total", 0))

        # streak（只记录不断链，不惩罚）
        srow = conn.execute(
            "SELECT streak_days, last_active_date FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        days = (srow["streak_days"] if srow else 0) or 0
        last_active = (srow["last_active_date"] if srow else None) or ""
        today = _today()
        yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).strftime("%Y-%m-%d")
        if last_active == today:
            streak_state = "active"
            streak_copy = f"连续 {days} 天，今天也来啦～"
        elif last_active == yesterday:
            streak_state = "pending"
            streak_copy = "今天回来就续上啦，随便学点什么都可以～"
        else:
            streak_state = "rest"
            streak_copy = "休息过一阵也没关系，呀呀一直都在。"

        # 呀呀陪伴态：等级与连续天数共同决定（前端 CSS 绘制，零素材）
        mood = _yaya_mood(lv["level"], days, streak_state)
        return {
            "tasks": tasks,
            "xp": {**xp, **lv},
            "streak": {"days": days, "state": streak_state, "copy": streak_copy},
            "yaya": {"mood": mood, "message": _yaya_message(mood, tasks, lv["level"])},
        }
    except Exception:  # noqa: BLE001 - 今日页永不 500
        return {
            "tasks": [], "xp": {**{"today": 0, "sources": {}, "total": 0}, **level_for_xp(0)},
            "streak": {"days": 0, "state": "rest", "copy": ""},
            "yaya": {"mood": "newcomer", "message": ""},
        }
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _yaya_mood(level: int, streak_days: int, streak_state: str) -> str:
    if level >= 5 or streak_days >= 21:
        return "soulmate"
    if level >= 3 or streak_days >= 7:
        return "oldfriend"
    if level >= 2 or (streak_state == "active" and streak_days >= 3):
        return "buddy"
    return "newcomer"


def _yaya_message(mood: str, tasks: list, level: int) -> str:
    """今日页呀呀的一句话（温和、不施压、禁负面词）。"""
    undone = [t for t in tasks if not t.get("done")]
    if not tasks:
        return "今天想做点什么都可以呀。"
    if not undone:
        return "今天的小目标都完成啦，明天呀呀还在这儿等你～"
    first = undone[0]["key"]
    by_key = {
        "review": "有几个词想见你啦，去复习一下下？",
        "read": "有一篇刚好适合你的小短文在等你。",
        "chat": "想跟我聊聊天吗？说错也没关系的。",
    }
    if mood == "newcomer":
        return by_key.get(first, "我们慢慢开始，一步就好。")
    if mood in ("buddy", "oldfriend"):
        return by_key.get(first, "今天也一起散个步吧。")
    return by_key.get(first, "见到你真好。")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
