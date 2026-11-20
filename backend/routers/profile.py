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


@router.get("/api/profile")
async def profile():
    data = db.get_profile()
    if data is None:
        raise ApiError(50001, 500, "用户档案不存在")
    return ok(data)


@router.get("/api/profile/skills")
async def profile_skills():
    """TASK-0055 水平画像（懒计算）：读时全量重放事件流 → EWMA → 快照。

    §5.4：画像是"练习侧写"非官方 CEFR 判定；不改 cefr_level 本体。
    """
    items = db.rebuild_skill_profile(db.DEFAULT_USER_ID)
    return ok({
        "items": items,
        "event_count": db.count_skill_events(db.DEFAULT_USER_ID),
    })


@router.get("/api/achievements")
async def achievements():
    """TASK-0058 成就 v1（懒计算）：读时从真实事件全量判定 + 幂等落库 + 新解锁计 XP。

    §5.3：判定源全为已落库数据，服务端常量不下放；未解锁返回灰态给牵引感。
    """
    result = db.evaluate_achievements(db.DEFAULT_USER_ID)
    return ok({
        "items": result["items"],
        "unlocked_count": result["unlocked_count"],
        "new_unlocked": result["new_codes"],
    })

@router.get("/api/retention")
async def retention():
    """TASK-0060 留存激励 v1（UX_PROGRESS_PLAN §D）：纯读现有表聚合，零新表。

    接着上次 / 今日小目标 / streak 正向文案 / 微进步；文案禁负面词，失败静默降级。
    """
    data = db.get_retention(db.DEFAULT_USER_ID)
    return ok(data)

