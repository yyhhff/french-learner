import json
import logging
import os
import re
import string
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

import ai
import assessment
import db
import exam
import gamify
import pronunciation
import srs

from common import *  # noqa: F403 — Wave 0 原样搬运，保持原单文件作用域的名称可见性

router = APIRouter()


# ---------------------------------------------------------------- v2 输入流 API（全部先于静态 mount 声明）

def _parse_int_param(raw, name: str, default: int, minimum: int, maximum: int | None = None) -> int:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise ApiError(40001, 400, f"{name} 必须是整数")
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError(40001, 400, f"{name} 超出允许范围")
    return value


async def _optional_json_body(request: Request) -> dict:
    """collect 的 Body 可选：空 body 视为 {}，否则必须是 JSON 对象。"""
    raw = await request.body()
    if not raw or not raw.strip():
        return {}
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        raise ApiError(40001, 400, "请求体不是合法 JSON")
    if not isinstance(body, dict):
        raise ApiError(40001, 400, "请求体必须是 JSON 对象")
    return body


@router.get("/api/input/levels")
async def input_levels():
    return ok(db.list_input_levels())


@router.get("/api/input/texts")
async def input_texts(
    level: str | None = None,
    limit: str | None = None,
    offset: str | None = None,
):
    if level is not None and level != "":
        if level not in ("A1", "A2", "B1", "B2"):
            raise ApiError(40001, 400, "level 必须是 A1/A2/B1/B2")
    else:
        level = None
    size = _parse_int_param(limit, "limit", 20, 1, 50)
    start = _parse_int_param(offset, "offset", 0, 0)
    return ok(db.list_input_texts(level=level, limit=size, offset=start))


@router.get("/api/input/texts/{text_id}")
async def input_text_detail(text_id: str):
    detail = db.get_input_text_detail(text_id)
    if detail is None:
        raise ApiError(40401, 404, f"语料不存在：{text_id}")
    return ok(detail)


@router.post("/api/input/texts/{text_id}/collect")
async def input_text_collect(text_id: str, request: Request):
    body = await _optional_json_body(request)
    words = body.get("words")
    if words is not None:
        if not isinstance(words, list):
            raise ApiError(40001, 400, "words 必须是字符串数组")
        cleaned = []
        for word in words:
            if not isinstance(word, str):
                raise ApiError(40001, 400, "words 元素必须是字符串")
            word = word.strip()
            if word:
                cleaned.append(word)
        words = cleaned  # 空数组 → db 层按“收全部”处理
    result = db.collect_input_words(text_id, words=words)
    if result is None:
        raise ApiError(40401, 404, f"语料不存在：{text_id}")
    return ok(result)


@router.post("/api/input/texts/{text_id}/complete")
async def input_text_complete(text_id: str):
    """TASK-0052：阅读完成落库（幂等）。滚动到文末时由前端调用，一篇只记一次。"""
    detail = db.get_input_text_detail(text_id)
    if detail is None:
        raise ApiError(40401, 404, f"语料不存在：{text_id}")
    first_time = db.mark_text_read(
        user_id=db.DEFAULT_USER_ID,
        text_id=text_id,
        cefr_level=detail.get("cefr_level"),
        title=detail.get("title"),
    )
    if first_time:
        # TASK-0055 阅读信号（α=0.30/0.20）：篇目 CEFR 越高 event_score 越高
        _READING_SCORE = {"A1": 55, "A2": 62, "B1": 70, "B2": 78, "C1": 85}
        lvl = detail.get("cefr_level") or "A2"
        rscore = _READING_SCORE.get(lvl, 62)
        _record_skill_events([
            ("reading", rscore, "input", text_id),
            ("vocabulary", max(40, rscore - 8), "input", text_id),
        ])
        # TASK-0070 v3.0：首读 +15xp（幂等 reading_logs 已保证只触发一次）
        gamify.award("read", 15, detail=text_id)
    return ok({
        "first_time": first_time,
        "read_count": db.count_read_texts(db.DEFAULT_USER_ID),
    })


def _level_score(level, current: str, target: str) -> int:
    if level == target:
        return 3
    if level == current:
        return 1
    li = db.CEFR_ORDER.index(level) if level in db.CEFR_ORDER else 0
    ti = db.CEFR_ORDER.index(target) if target in db.CEFR_ORDER else 0
    ci = db.CEFR_ORDER.index(current) if current in db.CEFR_ORDER else 0
    if li > ti:
        return -2
    if li < ci:
        return -1
    return 0


def _coverage_score(coverage) -> int:
    if coverage is None:
        return 0
    if 0.7 <= coverage <= 0.9:
        return 3
    if 0.5 <= coverage < 0.7:
        return 1
    if 0.9 < coverage <= 1.0:
        return 0
    if coverage < 0.5:
        return -2
    return 0


@router.get("/api/input/recommend")
async def input_recommend(
    exclude_ids: str | None = None,
    limit: str | None = None,
):
    # §6 limit 仅作参数校验（1~10）；data.text 是单个 InputTextDetail，取排序第一篇。
    _parse_int_param(limit, "limit", 1, 1, 10)
    excluded = set()
    if exclude_ids and exclude_ids.strip():
        excluded = {s.strip() for s in exclude_ids.split(",") if s.strip()}

    profile = db.get_profile() or {}
    current = profile.get("cefr_level")
    if current not in db.CEFR_ORDER:
        current = "A1"
    idx = max(0, db.CEFR_ORDER.index(current))
    # v2.2：A1 零基础留在 A1 台阶语料，不跳到 A2（否则零基础推荐断档）
    target = "A1" if current == "A1" else db.CEFR_ORDER[min(idx + 1, len(db.CEFR_ORDER) - 1)]

    candidates = [t for t in db.get_all_input_texts() if t["id"] not in excluded]
    if not candidates:
        return ok({"text": None, "target_level": target, "reason": "no_candidate"})

    mastered = db.get_mastered_words()
    scored = []
    for text in candidates:
        words = db.get_input_words(text["id"])
        coverage = None
        if words:
            known = sum(1 for w in words if w.get("word") in mastered)
            coverage = known / len(words)
        score = (
            _level_score(text["cefr_level"], current, target)
            + _coverage_score(coverage)
        )
        scored.append((score, text, coverage))

    has_coverage = any(c is not None for _, _, c in scored)
    pool = [x for x in scored if x[2] is not None] if has_coverage else scored
    pool.sort(key=lambda x: (-x[0], x[1]["sort_order"], x[1]["id"]))
    chosen = pool[0][1]
    detail = db.get_input_text_detail(chosen["id"])
    reason = "level_and_coverage" if has_coverage else "level_only_fallback"
    return ok({"text": detail, "target_level": target, "reason": reason})

