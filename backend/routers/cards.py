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
import pronunciation
import srs

from common import *  # noqa: F403 — Wave 0 原样搬运，保持原单文件作用域的名称可见性

router = APIRouter()


@router.get("/api/cards")
async def cards(scene_id: str | None = None):
    return ok(db.list_cards(scene_id=scene_id))


@router.post("/api/cards/{id}/review")
async def review(id: str, request: Request):
    try:
        card_id = int(id)
    except (TypeError, ValueError):
        raise ApiError(40001, 400, "卡片 id 必须是整数")

    body = await json_body(request)
    rating = body.get("rating")
    if (
        not isinstance(rating, int)
        or isinstance(rating, bool)
        or rating not in (1, 2, 3, 4)
    ):
        raise ApiError(40001, 400, "rating 必须是 1/2/3/4 的整数")

    state = db.get_review_state(card_id)
    if state is None:
        raise ApiError(40401, 404, f"卡片不存在：{card_id}")

    new_state, next_due, interval_days = srs.schedule(rating, state)
    db.update_review(card_id, new_state, next_due)

    # TASK-0055 记忆/词汇信号（α=0.25/0.20）： rating 3/4 视为记起，1/2 视为模糊
    good = rating >= 3
    _record_skill_events([
        ("memory", 75 if good else 40, "review", str(card_id)),
        ("vocabulary", 70 if good else 45, "review", str(card_id)),
    ])

    return ok({"next_due": next_due, "interval_days": interval_days})

@router.get("/api/review/due")
async def review_due(request: Request):
    """TASK-0057 到期复习队列（UX_PROGRESS_PLAN §5.2 冻结契约）。

    只在本用户进入复习入口时拉取，温和分页、不推送、无倒计时/红点。
    """
    qp = request.query_params
    try:
        limit = int(qp.get("limit", 20))
        offset = int(qp.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError(40001, 400, "limit/offset 必须是整数")
    if not 1 <= limit <= 100:
        raise ApiError(40001, 400, "limit 必须在 1..100 之间")
    if offset < 0:
        raise ApiError(40001, 400, "offset 不能为负")

    items = db.list_due_reviews(limit=limit, offset=offset)
    due_count = db.count_due_reviews()
    return ok({
        "items": items,
        "total": due_count,
        "today_count": due_count,
    })

