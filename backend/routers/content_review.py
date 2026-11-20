"""v2.3 内容工厂审校台 API（内部工具，不影响面客端点）。

端点：
- GET  /api/content/review/queue   候选审校队列（状态 + 校验结论）
- POST /api/content/review/approve  {slot, reviewer?}  通过单条并入 texts.json
- POST /api/content/review/reject   {slot, note?}       否决单条
- POST /api/content/review/approve-all  {reviewer?}     批量通过已校验候选
- POST /api/content/review/veto     {text_id, note?}    人工否决已入库条目（更正通道）
- GET  /api/content/audio/{text_id}/{seq}  取落盘音频（由 audio_batch 生成）

所有写操作都经 content_pipeline.review_store（唯一可写 texts.json 的通道），且记录审计。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from common import ApiError, json_body, ok

router = APIRouter()

# content_pipeline 在项目根，不在 backend sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from content_pipeline import review_store  # noqa: E402


@router.get("/api/content/review/queue")
async def review_queue():
    return ok(review_store.list_queue())


@router.post("/api/content/review/approve")
async def review_approve(request: Request):
    body = await json_body(request)
    slot = str(body.get("slot", "")).strip()
    if not slot:
        raise ApiError(40001, 400, "缺少 slot")
    result = review_store.approve(slot, str(body.get("reviewer") or "web-reviewer"))
    return ok(result)


@router.post("/api/content/review/reject")
async def review_reject(request: Request):
    body = await json_body(request)
    slot = str(body.get("slot", "")).strip()
    if not slot:
        raise ApiError(40001, 400, "缺少 slot")
    result = review_store.reject(slot, str(body.get("reviewer") or "web-reviewer"), str(body.get("note") or ""))
    return ok(result)


@router.post("/api/content/review/approve-all")
async def review_approve_all(request: Request):
    body = await json_body(request)
    reviewer = str(body.get("reviewer") or "ai-reviewer-v2.3")
    return ok(review_store.approve_all_validated(reviewer))


@router.post("/api/content/review/veto")
async def review_veto(request: Request):
    body = await json_body(request)
    text_id = str(body.get("text_id", "")).strip()
    if not text_id:
        raise ApiError(40001, 400, "缺少 text_id")
    result = review_store.veto(text_id, str(body.get("reviewer") or "web-reviewer"), str(body.get("note") or ""))
    return ok(result)


@router.get("/api/content/audio/{text_id}/{seq}")
async def content_audio(text_id: str, seq: int):
    """返回批量生成的落盘音频；不存在返回 404（前端可回退在线 TTS）。"""
    from content_pipeline.paths import AUDIO_DIR

    path = AUDIO_DIR / text_id / f"{seq}.mp3"
    if not path.is_file():
        return Response(status_code=404)
    return Response(
        content=path.read_bytes(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "public, max-age=604800"},
    )
