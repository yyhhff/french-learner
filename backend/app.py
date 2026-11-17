"""呀呀法语 API 入口：路由、CORS、请求校验、统一响应包裹、静态文件托管。

启动流程：建表（若不存在）→ 空库灌入 seed → 提供服务。
注意：必须先声明全部 /api 路由，最后再 mount 静态目录，避免 /api 被静态接管。
"""
from __future__ import annotations

import json
import logging
import os
import re
import string
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import ai
import db
import srs
import seed
import seed_input

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


@app.post("/api/translate")
async def translate(request: Request):
    """批量法语→中文，给对话气泡配译文。失败不抛 500，对应位置返回 null。"""
    body = await json_body(request)
    texts = body.get("texts")
    if not isinstance(texts, list) or not texts:
        raise ApiError(40001, 400, "缺少必填字段 texts（非空数组）")
    if len(texts) > 10:
        raise ApiError(40001, 400, "一次最多翻译 10 条")
    for t in texts:
        if not isinstance(t, str) or len(t) > 500:
            raise ApiError(40001, 400, "texts 每项必须是 500 字以内的字符串")
    return ok({"translations": ai.translate_to_zh(texts)})


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


@app.get("/api/tts")
async def tts(text: str = ""):
    """转发文本到本地语音服务合成高质量法语朗读（mp3 音频流）。

    语音服务不可用/失败时抛 ApiError，前端据此回退浏览器 SpeechSynthesis，
    绝不因为朗读失败中断对话。
    """
    text = (text or "").strip()
    if not text:
        raise ApiError(40001, 400, "空文本")
    qs = urllib.parse.urlencode({"text": text})
    try:
        with urllib.request.urlopen(
            ASR_SERVICE_URL + "/tts?" + qs, timeout=30
        ) as resp:
            audio = resp.read()
    except urllib.error.HTTPError as exc:
        raise ApiError(50001, 500, f"语音合成失败（语音服务返回 {exc.code}）")
    except Exception as exc:  # noqa: BLE001
        logger.warning("语音合成服务不可用：%s", exc)
        raise ApiError(50001, 500, "语音合成服务暂不可用")
    if not audio:
        raise ApiError(50001, 500, "朗读音频为空")
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "public, max-age=604800"},
    )


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


@app.get("/api/input/levels")
async def input_levels():
    return ok(db.list_input_levels())


@app.get("/api/input/texts")
async def input_texts(
    level: str | None = None,
    limit: str | None = None,
    offset: str | None = None,
):
    if level is not None and level != "":
        if level not in ("A2", "B1", "B2"):
            raise ApiError(40001, 400, "level 必须是 A2/B1/B2")
    else:
        level = None
    size = _parse_int_param(limit, "limit", 20, 1, 50)
    start = _parse_int_param(offset, "offset", 0, 0)
    return ok(db.list_input_texts(level=level, limit=size, offset=start))


@app.get("/api/input/texts/{text_id}")
async def input_text_detail(text_id: str):
    detail = db.get_input_text_detail(text_id)
    if detail is None:
        raise ApiError(40401, 404, f"语料不存在：{text_id}")
    return ok(detail)


@app.post("/api/input/texts/{text_id}/collect")
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


@app.get("/api/input/recommend")
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
    target = db.CEFR_ORDER[min(idx + 1, len(db.CEFR_ORDER) - 1)]

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


# ---------------------------------------------------------------- 启动初始化

db.init_db()
if db.is_empty():
    logger.info("空库，灌入种子数据…")
    seed.seed_if_empty()
seed_input.load_input_corpus()  # 新增：每次启动同步语料（幂等，文件缺失不阻断）

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
