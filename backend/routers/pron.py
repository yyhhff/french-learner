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


# ---------------------------------------------------------------- 零基础读音规则学习 API（先于静态 mount 声明）
# 契约 PRONUNCIATION_CONTRACT.md v1.0 §3：4 端点；错误码仅 0/40001/40401/50001。

@router.get("/api/pronunciation/rules")
async def pronunciation_rules(group: str | None = None):
    """规则摘要列表（小册子索引）；group 省略/空=不过滤，非空须为 8 个合法组名之一。"""
    if group:
        if group not in pronunciation.GROUPS:
            raise ApiError(40001, 400, f"非法分组：{group}")
    else:
        group = None
    return ok(pronunciation.list_rules(group))


@router.get("/api/pronunciation/rules/{rule_id}")
async def pronunciation_rule_detail(rule_id: str):
    """单条规则完整详情（10 字段）；不存在 → 40401。"""
    detail = pronunciation.get_rule(rule_id)
    if detail is None:
        raise ApiError(40401, 404, f"读音规则不存在：{rule_id}")
    return ok(detail)


@router.get("/api/pronunciation/progress")
async def pronunciation_progress_get():
    """当前用户掌握度：统计 + 明细；total_rules 动态取规则缓存长度，不硬编码。"""
    data = db.get_progress(db.DEFAULT_USER_ID)
    view = {
        "user_id": data["user_id"],
        "total_rules": len(pronunciation.load_rules()),
        "seen_count": data["seen_count"],
        "learned_count": data["learned_count"],
        "confident_count": data["confident_count"],
        "learned_total": data["learned_total"],
        "items": data["items"],
    }
    return ok(view)


@router.post("/api/pronunciation/progress")
async def pronunciation_progress_update(request: Request):
    """更新某规则掌握状态（幂等 upsert）；practice_count 一律忽略并服务端 +1（裁决④）。"""
    body = await json_body(request)
    rule_id = body.get("rule_id")
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise ApiError(40001, 400, "缺少必填字段 rule_id")
    rule_id = rule_id.strip()
    if pronunciation.get_rule(rule_id) is None:
        raise ApiError(40401, 404, f"读音规则不存在：{rule_id}")

    stage = body.get("stage")
    if stage is not None and stage not in ("seen", "learned", "confident"):
        raise ApiError(40001, 400, "stage 必须是 seen/learned/confident")

    # practice_count 客户端传入一律忽略：服务端累加，防重复提交丢计数（裁决④）
    raw_self = body.get("self_assessed")
    self_assessed: int | None = None
    if raw_self is not None:
        if isinstance(raw_self, bool):  # bool 是 int 子类，须先判
            self_assessed = 1 if raw_self else 0
        elif isinstance(raw_self, int) and raw_self in (0, 1):
            self_assessed = raw_self
        else:
            raise ApiError(40001, 400, "self_assessed 必须是 0/1 或 bool")

    item = db.upsert_progress(
        db.DEFAULT_USER_ID, rule_id, stage=stage, self_assessed=self_assessed
    )
    return ok(item)

