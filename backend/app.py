"""呀呀法语 API 入口：装配、中间件、异常处理、router 注册、启动初始化、静态托管。

Wave 0（TASK-0064）：原 1137 行单文件按域拆为 backend/routers/<域>.py，
app.py 只保留装配职责；共享件（ApiError/ok/ROADMAP_DEFS 等）在 backend/common.py。
启动流程：建表（若不存在）→ 空库灌入 seed → 提供服务。
注意：必须先 include 全部 /api 路由，最后再 mount 静态目录，避免 /api 被静态接管。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import assessment
import db
import exam
import pronunciation
import seed
import seed_input
from common import ApiError, logger

from routers import (
    asr,
    assessment as assessment_router,
    cards,
    chat,
    content_review,
    exam as exam_router,
    feedback,
    grammar as grammar_router,
    input as input_router,
    pron,
    pron_coach,
    profile,
    roadmap,
    translate,
    tts,
)

app = FastAPI(title="呀呀法语 YaYa French", version="1.0.0")

# 契约 4.3：CORS 参数逐字使用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------- 统一异常


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


# ---------------------------------------------------------------- 路由装配（36+2 端点，TASK-0078 增 /api/grammar/*）
for _router in (
    chat.router,
    translate.router,
    cards.router,
    profile.router,
    roadmap.router,
    feedback.router,
    asr.router,
    tts.router,
    input_router.router,
    assessment_router.router,
    exam_router.router,
    pron.router,
    pron_coach.router,
    content_review.router,
    grammar_router.router,
):
    app.include_router(_router)

# ---------------------------------------------------------------- 启动初始化

db.init_db()
if db.is_empty():
    logger.info("空库，灌入种子数据…")
    seed.seed_if_empty()
db.ensure_profile_initialized()  # TASK-0040：演示假值清零迁移（幂等）
seed_input.load_input_corpus()  # 新增：每次启动同步语料（幂等，文件缺失不阻断）
try:  # 定级题库：幂等加载，文件缺失/异常不阻断启动（其余 15 端点正常）
    assessment.load_questions()
except Exception as exc:  # noqa: BLE001
    logger.warning("定级题库加载异常，题库降级为空：%s", exc)
try:  # 考级试卷：幂等加载，文件缺失/异常不阻断启动（其余 18 端点正常）
    exam.load_papers()
except Exception as exc:  # noqa: BLE001
    logger.warning("考级试卷加载异常，试卷降级为空：%s", exc)
try:  # 读音规则：幂等加载，文件缺失/异常不阻断启动（4 端点从缓存降级）
    pronunciation.load_rules()
except Exception as exc:  # noqa: BLE001
    logger.warning("读音规则加载异常，规则降级为空：%s", exc)

# ---------------------------------------------------------------- 静态托管（最后 mount）

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.middleware("http")
async def static_revalidate_cache(request: Request, call_next):
    """前端静态资源一律协商缓存（TASK-0068 缺陷修复）。

    StaticFiles 响应原本无 Cache-Control，浏览器对 ES modules 启发式缓存旧文件，
    改前端代码后用户需手动清缓存才能生效（发音教练重叠缺陷即因此未及时修复）。
    no-cache = 每次协商（etag 命中 304），开发零摩擦且线上性能无损；仅限前端路径。
    """
    response = await call_next(request)
    p = request.url.path
    if p == "/" or p.startswith(("/js/", "/styles.css", "/index.html", "/review.html")):
        response.headers["Cache-Control"] = "no-cache"
    return response


if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
else:
    logger.warning(
        "frontend 目录不存在（%s），跳过静态托管；API 仍可正常访问。", FRONTEND_DIR
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("YAYA_BACKEND_PORT", "8000")))
