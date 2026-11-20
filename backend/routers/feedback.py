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


# ---------------------------------------------------------------- 使用反馈（TASK-0062）

@router.get("/api/feedback/categories")
async def feedback_categories():
    """TASK-0062 反馈预设方向（code+label）：前后端单一数据源，前端打开浮层时懒拉。"""
    return ok(db.feedback_categories())


@router.post("/api/feedback")
async def post_feedback(request: Request):
    """TASK-0062 提交一条使用反馈：预设方向 + 文字建议（+ 可选联系方式）。

    category 必须是 FEEDBACK_CATEGORIES 的 key；content 去空白后非空、≤1000 字。
    """
    body = await json_body(request)
    category = body.get("category")
    content = body.get("content")
    contact = body.get("contact")
    if not isinstance(category, str) or category not in db.FEEDBACK_CATEGORIES:
        raise ApiError(40001, 400, "feedback 方向无效")
    if not isinstance(content, str) or not content.strip():
        raise ApiError(40001, 400, "请写下想说的话")
    if len(content.strip()) > 1000:
        raise ApiError(40001, 400, "建议内容不能超过 1000 字")
    if contact is not None and not isinstance(contact, str):
        raise ApiError(40001, 400, "联系方式格式无效")
    if isinstance(contact, str) and len(contact.strip()) > 200:
        raise ApiError(40001, 400, "联系方式不能超过 200 字")
    result = db.submit_feedback(category, content, contact, db.DEFAULT_USER_ID)
    return ok(result)


@router.get("/api/feedback/summary")
async def feedback_summary():
    """TASK-0062 反馈汇总（版本优化决策依据）：按方向计数 + 最近原文。"""
    return ok(db.get_feedback_summary(db.DEFAULT_USER_ID))

