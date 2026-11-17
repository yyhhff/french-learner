"""呀呀法语 API 入口：路由、CORS、请求校验、统一响应包裹、静态文件托管。

启动流程：建表（若不存在）→ 空库灌入 seed → 提供服务。
注意：必须先声明全部 /api 路由，最后再 mount 静态目录，避免 /api 被静态接管。
"""
from __future__ import annotations

import logging
import os
import string
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import ai
import db
import srs
import seed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yaya.app")

app = FastAPI(title="呀呀法语 YaYa French", version="1.0.0")

# 契约 4.3：CORS 参数逐字使用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------- 统一响应 / 异常

class ApiError(Exception):
    def __init__(self, code: int, http_status: int, message: str):
        self.code = code
        self.http_status = http_status
        self.message = message
        super().__init__(message)


def ok(data) -> JSONResponse:
    return JSONResponse(
        status_code=200, content={"code": 0, "data": data, "message": "ok"}
    )


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "data": None, "message": exc.message},
    )


@app.exception_handler(Exception)
async def generic_error_handler(_request: Request, exc: Exception):
    # 禁止把 traceback 返回前端；仅在服务端日志记录
    logger.exception("未捕获异常：%s", exc)
    return JSONResponse(
        status_code=500,
        content={"code": 50001, "data": None, "message": "服务内部错误"},
    )


async def json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise ApiError(40001, 400, "请求体不是合法 JSON")
    if not isinstance(body, dict):
        raise ApiError(40001, 400, "请求体必须是 JSON 对象")
    return body


_TRIM_CHARS = string.punctuation + "«»„“”…¿¡·°\t\n\r "


def normalize_user_text(text: str) -> str:
    return str(text).strip().strip(_TRIM_CHARS).strip()


# ---------------------------------------------------------------- 路由（全部先声明）

@app.get("/api/health")
async def health():
    return ok({"status": "ok", "version": "1.0.0", "time": db.now_iso()})


@app.get("/api/scenes")
async def scenes():
    return ok(db.list_scenes())


@app.get("/api/scenes/{scene_id}")
async def scene_detail(scene_id: str):
    scene = db.get_scene(scene_id)
    if scene is None:
        raise ApiError(40401, 404, f"场景不存在：{scene_id}")
    data = dict(scene)
    data["start_dialogue"] = db.get_start_dialogue(scene_id)
    return ok(data)


@app.post("/api/chat")
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

    return ok(result.to_dict())


@app.get("/api/cards")
async def cards(scene_id: str | None = None):
    return ok(db.list_cards(scene_id=scene_id))


@app.post("/api/cards/{id}/review")
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

    return ok({"next_due": next_due, "interval_days": interval_days})


@app.get("/api/profile")
async def profile():
    data = db.get_profile()
    if data is None:
        raise ApiError(50001, 500, "用户档案不存在")
    return ok(data)


# ---------------------------------------------------------------- 启动初始化

db.init_db()
if db.is_empty():
    logger.info("空库，灌入种子数据…")
    seed.seed_if_empty()

# ---------------------------------------------------------------- 静态托管（最后 mount）

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
else:
    logger.warning(
        "frontend 目录不存在（%s），跳过静态托管；API 仍可正常访问。", FRONTEND_DIR
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
