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
import grammar
import pronunciation
import srs

from common import *  # noqa: F403 — Wave 0 原样搬运，保持原单文件作用域的名称可见性

router = APIRouter()


@router.get("/api/health")
async def health():
    return ok({"status": "ok", "version": "1.0.0", "time": db.now_iso()})


@router.get("/api/scenes")
async def scenes():
    return ok(db.list_scenes())


@router.get("/api/scenes/{scene_id}")
async def scene_detail(scene_id: str):
    scene = db.get_scene(scene_id)
    if scene is None:
        raise ApiError(40401, 404, f"场景不存在：{scene_id}")
    data = dict(scene)
    data["start_dialogue"] = db.get_start_dialogue(scene_id)
    return ok(data)

def _record_skill_events(events: list) -> None:
    """TASK-0055：画像事件只写流水不更新画像（懒计算）；失败不阻塞主流程。"""
    try:
        db.record_skill_events(db.DEFAULT_USER_ID, events)
    except Exception:  # noqa: BLE001 — 画像是增益功能，任何异常都不影响提交本身
        pass


@router.post("/api/chat")
async def chat(request: Request):
    body = await json_body(request)

    scene_id = body.get("scene_id")
    if not isinstance(scene_id, str) or not scene_id.strip():
        raise ApiError(40001, 400, "缺少必填字段 scene_id")
    scene_id = scene_id.strip()
    if db.get_scene(scene_id) is None:
        raise ApiError(40401, 404, f"场景不存在：{scene_id}")

    raw_text = body.get("user_text")
    if not isinstance(raw_text, str):
        raise ApiError(40001, 400, "缺少必填字段 user_text")
    user_text = normalize_user_text(raw_text)
    if not user_text:
        raise ApiError(40001, 400, "user_text 不能为空")
    if len(user_text) > 500:
        raise ApiError(40001, 400, "user_text 长度不能超过 500")

    history = body.get("history", [])
    if history is None:
        history = []
    if not isinstance(history, list):
        raise ApiError(40001, 400, "history 必须是数组")
    history = history[-10:]

    # 重述（纠错永远不是错误；recast 内部已对 LLM 失败做降级）
    result = ai.recast(scene_id, user_text, history)

    user_id = db.DEFAULT_USER_ID
    db.add_dialogue_turn(
        user_id=user_id,
        scene_id=scene_id,
        role="user",
        fr=user_text,
        cn="（你刚说的）",
    )
    is_correction = bool(result.recast_of)
    db.add_dialogue_turn(
        user_id=user_id,
        scene_id=scene_id,
        role="assistant",
        fr=result.ai_text,
        cn="（呀呀的自然重述）" if is_correction else "（呀呀的回应）",
        recast_of=result.recast_of,
        explanation=result.explanation,
        is_correction=is_correction,
    )
    # 每轮 +10 XP，本轮共 2 轮
    db.update_user_activity(user_id, xp_delta=20)

    # TASK-0055 口语信号（弱信号 α=0.15）：流利度按"开口即练习"，语法按是否被重述纠错
    _record_skill_events([
        ("speaking", 70 if not is_correction else 55, "chat", scene_id),
        ("fluency", 65, "chat", scene_id),
        ("grammar", 65 if not is_correction else 45, "chat", scene_id),
    ])

    # TASK-0078 v3.3：recast 纠错轮落语法错误画像；同类第 3 次 → 响应附 grammar_card
    # （on_recast 内部吞异常永不抛，画像失败不影响对话主流程）
    payload = result.to_dict()
    grammar_card = grammar.on_recast(user_id, scene_id, user_text, result)
    if grammar_card:
        payload["grammar_card"] = grammar_card

    return ok(payload)


@router.get("/api/chat/history")
async def chat_history(scene_id: str | None = None, limit: str | None = None):
    """TASK-0040：读回真实对话历史（排除种子预置行），供前端进入场景时恢复。"""
    scene_id = (scene_id or "").strip() or None
    if scene_id and db.get_scene(scene_id) is None:
        raise ApiError(40401, 404, f"场景不存在：{scene_id}")
    n = _parse_int_param(limit, "limit", 50, 1, 200)
    items = db.list_dialogue_history(scene_id=scene_id, limit=n)
    return ok({"items": items, "has_more": len(items) == n})


@router.delete("/api/chat/history")
async def chat_history_clear(scene_id: str | None = None):
    """重置对话：清除该场景的持久化对话轮（保留种子开场白）。scene_id 缺省时清全部场景。"""
    scene_id = (scene_id or "").strip() or None
    if scene_id and db.get_scene(scene_id) is None:
        raise ApiError(40401, 404, f"场景不存在：{scene_id}")
    deleted = db.clear_dialogue_history(user_id=db.DEFAULT_USER_ID, scene_id=scene_id)
    return ok({"deleted": deleted})

