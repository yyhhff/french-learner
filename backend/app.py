"""呀呀法语 API 入口：路由、CORS、请求校验、统一响应包裹、静态文件托管。

启动流程：建表（若不存在）→ 空库灌入 seed → 提供服务。
注意：必须先声明全部 /api 路由，最后再 mount 静态目录，避免 /api 被静态接管。
"""
from __future__ import annotations

import logging
import os
import re
import string
import urllib.error
import urllib.request
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


def _parse_multipart(body: bytes, content_type: str) -> tuple[bytes, str, str]:
    """极简 multipart 解析：提取第一个文件字段的字节、文件名、content-type。

    只用标准库，避免为主后端引入 python-multipart 依赖。
    """
    m = re.search(r"boundary=(?:\"([^\"]+)\"|([^;\s]+))", content_type)
    if not m:
        raise ApiError(40001, 400, "缺少 multipart boundary")
    boundary = (m.group(1) or m.group(2)).encode("utf-8")
    parts = body.split(b"--" + boundary)
    for part in parts:
        if b"Content-Disposition:" not in part or b"filename=" not in part:
            continue
        header_blob, _, payload = part.partition(b"\r\n\r\n")
        header = header_blob.decode("utf-8", "ignore")
        fn = re.search(r'filename="([^"]*)"', header)
        ct = re.search(r"Content-Type:\s*([^\r\n]+)", header)
        # 去掉payload末尾的 \r\n
        payload = payload.rstrip(b"\r\n")
        return payload, (fn.group(1) if fn else "audio.webm"), (
            ct.group(1).strip() if ct else "application/octet-stream"
        )
    raise ApiError(40001, 400, "multipart 中没有找到音频文件字段")


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


# ---------------------------------------------------------------- 本地 ASR 代理

ASR_SERVICE_URL = os.environ.get(
    "YAYA_ASR_URL", "http://127.0.0.1:8010"
).rstrip("/")


@app.get("/api/asr/status")
async def asr_status():
    """前端启动时探测本地 ASR 服务是否可用，决定是否显示麦克风。"""
    try:
        with urllib.request.urlopen(ASR_SERVICE_URL + "/health", timeout=2) as resp:
            import json

            info = json.loads(resp.read().decode("utf-8"))
        return ok({"available": True, **info})
    except Exception:  # noqa: BLE001 - 服务未起是正常状态
        return ok({"available": False})


@app.post("/api/asr/transcribe")
async def asr_transcribe(request: Request):
    """转发音频到本地 ASR 服务，返回转写文本。

    ASR 服务未启动或失败时返回 40001 + 明确提示，前端据此降级为打字，
    绝不因为语音不可用而中断对话主流程。
    """
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    audio, filename, audio_ct = _parse_multipart(body, content_type)
    language = "fr"
    lang_m = re.search(r'name="language"\r\n\r\n([^\r\n]+)', body.decode("latin-1", "ignore"))
    if lang_m:
        language = lang_m.group(1).strip() or "fr"
    if not audio:
        raise ApiError(40001, 400, "空音频文件")

    boundary = "----yayaAsrBoundary"

    def part(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")

    body = b"".join(
        [
            part("language", language),
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {audio_ct or 'application/octet-stream'}\r\n\r\n".encode(
                "utf-8"
            ),
            audio,
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    req = urllib.request.Request(
        ASR_SERVICE_URL + "/transcribe",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            import json

            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ApiError(50001, 500, f"语音转写失败（ASR 服务返回 {exc.code}）")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ASR 服务不可用：%s", exc)
        raise ApiError(
            40001,
            400,
            "本地语音服务未启动，请改用打字，或启动 ASR 服务后再试。",
        )

    if not result.get("ok"):
        raise ApiError(50001, 500, result.get("error", "语音转写失败"))
    text = (result.get("text") or "").strip()
    if not text:
        raise ApiError(40001, 400, "没听清，请再说一次或直接打字")
    return ok({"text": text, "language": result.get("language")})


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
