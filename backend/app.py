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
import assessment
import db
import exam
import pronunciation
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


def _record_skill_events(events: list) -> None:
    """TASK-0055：画像事件只写流水不更新画像（懒计算）；失败不阻塞主流程。"""
    try:
        db.record_skill_events(db.DEFAULT_USER_ID, events)
    except Exception:  # noqa: BLE001 — 画像是增益功能，任何异常都不影响提交本身
        pass


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

    # TASK-0055 口语信号（弱信号 α=0.15）：流利度按"开口即练习"，语法按是否被重述纠错
    _record_skill_events([
        ("speaking", 70 if not is_correction else 55, "chat", scene_id),
        ("fluency", 65, "chat", scene_id),
        ("grammar", 65 if not is_correction else 45, "chat", scene_id),
    ])

    return ok(result.to_dict())


@app.get("/api/chat/history")
async def chat_history(scene_id: str | None = None, limit: str | None = None):
    """TASK-0040：读回真实对话历史（排除种子预置行），供前端进入场景时恢复。"""
    scene_id = (scene_id or "").strip() or None
    if scene_id and db.get_scene(scene_id) is None:
        raise ApiError(40401, 404, f"场景不存在：{scene_id}")
    n = _parse_int_param(limit, "limit", 50, 1, 200)
    items = db.list_dialogue_history(scene_id=scene_id, limit=n)
    return ok({"items": items, "has_more": len(items) == n})


@app.delete("/api/chat/history")
async def chat_history_clear(scene_id: str | None = None):
    """重置对话：清除该场景的持久化对话轮（保留种子开场白）。scene_id 缺省时清全部场景。"""
    scene_id = (scene_id or "").strip() or None
    if scene_id and db.get_scene(scene_id) is None:
        raise ApiError(40401, 404, f"场景不存在：{scene_id}")
    deleted = db.clear_dialogue_history(user_id=db.DEFAULT_USER_ID, scene_id=scene_id)
    return ok({"deleted": deleted})


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

    # TASK-0055 记忆/词汇信号（α=0.25/0.20）： rating 3/4 视为记起，1/2 视为模糊
    good = rating >= 3
    _record_skill_events([
        ("memory", 75 if good else 40, "review", str(card_id)),
        ("vocabulary", 70 if good else 45, "review", str(card_id)),
    ])

    return ok({"next_due": next_due, "interval_days": interval_days})


@app.get("/api/review/due")
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


@app.get("/api/profile")
async def profile():
    data = db.get_profile()
    if data is None:
        raise ApiError(50001, 500, "用户档案不存在")
    return ok(data)


@app.get("/api/profile/skills")
async def profile_skills():
    """TASK-0055 水平画像（懒计算）：读时全量重放事件流 → EWMA → 快照。

    §5.4：画像是"练习侧写"非官方 CEFR 判定；不改 cefr_level 本体。
    """
    items = db.rebuild_skill_profile(db.DEFAULT_USER_ID)
    return ok({
        "items": items,
        "event_count": db.count_skill_events(db.DEFAULT_USER_ID),
    })


@app.get("/api/achievements")
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


# ---------------------------------------------------------------- 本地 ASR 代理

ASR_SERVICE_URL = os.environ.get(
    "YAYA_ASR_URL", "http://127.0.0.1:8011"
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
    # 上下文热词：前端收集的法语词，含重音字母，须按 UTF-8 解码
    hints = ""
    hints_m = re.search(r'name="hints"\r\n\r\n([^\r\n]*)', body.decode("utf-8", "ignore"))
    if hints_m:
        hints = hints_m.group(1).strip()[:1000]
    # 前一句对话整句作为 initial_prompt 上下文（UTF-8，含法语重音）
    context = ""
    ctx_m = re.search(r'name="context"\r\n\r\n([^\r\n]*)', body.decode("utf-8", "ignore"))
    if ctx_m:
        context = ctx_m.group(1).strip()[:200]
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
            part("hints", hints),
            part("context", context),
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
    # 置信度字段由 ASR 服务提供：默认 0.0 / False，容错外部字段类型
    try:
        confidence = float(result.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return ok({
        "text": text,
        "language": result.get("language"),
        "raw_text": result.get("raw_text"),
        "corrected": bool(result.get("corrected")),
        "confidence": confidence,
        "low_confidence": bool(result.get("low_confidence", False)),
    })


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


@app.post("/api/input/texts/{text_id}/complete")
async def input_text_complete(text_id: str):
    """TASK-0052：阅读完成落库（幂等）。滚动到文末时由前端调用，一篇只记一次。"""
    detail = db.get_input_text_detail(text_id)
    if detail is None:
        raise ApiError(40401, 404, f"语料不存在：{text_id}")
    first_time = db.mark_text_read(
        user_id=db.DEFAULT_USER_ID,
        text_id=text_id,
        cefr_level=detail.get("cefr_level"),
        title=detail.get("title"),
    )
    if first_time:
        # TASK-0055 阅读信号（α=0.30/0.20）：篇目 CEFR 越高 event_score 越高
        _READING_SCORE = {"A1": 55, "A2": 62, "B1": 70, "B2": 78, "C1": 85}
        lvl = detail.get("cefr_level") or "A2"
        rscore = _READING_SCORE.get(lvl, 62)
        _record_skill_events([
            ("reading", rscore, "input", text_id),
            ("vocabulary", max(40, rscore - 8), "input", text_id),
        ])
    return ok({
        "first_time": first_time,
        "read_count": db.count_read_texts(db.DEFAULT_USER_ID),
    })


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


# ---------------------------------------------------------------- 阶段0 定级 API（先于静态 mount 声明）
# 契约 ARCHITECTURE_PLACEMENT.md v1.1 §3：取卷隐藏答案；交卷按 id 判分 + 幂等写回。

@app.get("/api/assessment/questions")
async def assessment_questions():
    """取卷：公开视图 5 字段，绝不下发 answer_idx / explanation_zh。"""
    public = assessment.public_questions(assessment.load_questions())
    return ok({"questions": public, "total": len(public)})


@app.post("/api/assessment/submit")
async def assessment_submit(request: Request):
    """交卷判分：先校验 → 判分定级 → 幂等写回 → 返回 PlacementResult。"""
    questions = assessment.load_questions()
    if not questions:  # §6.1.3 先判题库，题库空返回 50001 而非答案数量错
        raise ApiError(50001, 500, "定级题库暂不可用，无法判分")

    body = await json_body(request)
    answers = body.get("answers")
    if not isinstance(answers, list) or not answers:
        raise ApiError(40001, 400, "answers 必须是非空数组")
    if len(answers) != len(questions):
        raise ApiError(40001, 400, "答案数量与题目数量不一致")

    question_ids = {q["id"] for q in questions}
    seen_ids: set = set()
    for item in answers:
        if not isinstance(item, dict):
            raise ApiError(40001, 400, "answers 元素必须是对象")
        answer_id = item.get("id")
        if not isinstance(answer_id, str) or not answer_id.strip():
            raise ApiError(40001, 400, "答案项 id 不能为空")
        if answer_id not in question_ids:
            raise ApiError(40001, 400, f"题目不存在：{answer_id}")
        if answer_id in seen_ids:
            raise ApiError(40001, 400, f"题目 id 重复：{answer_id}")
        seen_ids.add(answer_id)
        answer_idx = item.get("answer_idx")
        if not isinstance(answer_idx, int) or isinstance(answer_idx, bool):
            raise ApiError(40001, 400, "answer_idx 必须是整数")
        if not 0 <= answer_idx <= 3:
            raise ApiError(40001, 400, "答案索引超出范围")
    if seen_ids != question_ids:
        raise ApiError(40001, 400, "答案题目集合与题库不一致")

    total = len(questions)
    result = assessment.grade(answers, questions)
    interpretation = assessment.interpretation_zh(
        result["level"], result["weak_skill"], result["score"], total, result["rate"]
    )

    user_id = db.DEFAULT_USER_ID
    if db.get_latest_attempt(user_id, "placement") is not None:
        persisted = False  # §6.4 已定级：不写库、不更新 cefr_level，仍返回本次算分
    else:
        detail = {
            "total": total,
            "level": result["level"],
            "rate": result["rate"],
            "weighted_score": result["weighted_score"],
            "weak_skill": result["weak_skill"],
            "interpretation_zh": interpretation,
            "answers": result["correct_flags"],
        }
        db.add_attempt(user_id, "placement", result["score"], detail)
        db.set_user_cefr_level(user_id, result["level"])
        persisted = True
        # TASK-0055 定级锚点（强信号 α=0.80）：rate 映射 0-100，一次定级锚定全部 7 维基线
        _record_skill_events([
            (dim, round(result["rate"] * 100, 1), "placement", f"attempt:{result['level']}")
            for dim in db.SKILL_DIMS
        ])

    return ok({
        "score": result["score"],
        "total": total,
        "weighted_score": result["weighted_score"],
        "level": result["level"],
        "interpretation_zh": interpretation,
        "persisted": persisted,
    })


# ---------------------------------------------------------------- 阶段4 考级冲刺 API（先于静态 mount 声明）
# 契约 ARCHITECTURE_EXAM.md v1.0 §3：列表不含题目、详情白名单脱敏、交卷每次写一条 records。

@app.get("/api/exam/papers")
async def exam_papers():
    """试卷列表（PaperSummary[]）；缓存空降级 []，不抛 500。"""
    return ok(exam.list_papers())


@app.get("/api/exam/papers/{paper_id}")
async def exam_paper_detail(paper_id: str):
    """试卷详情公开视图；不存在 → 40401。"""
    detail = exam.get_public_paper(paper_id)
    if detail is None:
        raise ApiError(40401, 404, "试卷不存在，换一套试试～")
    return ok(detail)


@app.post("/api/exam/submit")
async def exam_submit(request: Request):
    """交卷：校验 → 判分（GLM 失败仅降级该题）→ 每次写一条 attempts(kind='exam')。"""
    papers = exam.load_papers()
    if not papers:  # §5.1 先判缓存，试卷不可用返回 50001 而非答案数量错
        raise ApiError(50001, 500, "试卷暂不可用，无法判分")

    body = await json_body(request)
    paper_id = body.get("paper_id")
    if not isinstance(paper_id, str) or not paper_id.strip():
        raise ApiError(40001, 400, "缺少必填字段 paper_id")
    paper = exam.get_paper(paper_id)
    if paper is None:
        raise ApiError(40001, 400, "试卷不存在，换一套试试～")

    questions = paper["questions"]
    question_index = {q["id"]: q for q in questions}
    question_ids = set(question_index)
    answers = body.get("answers")
    if not isinstance(answers, list) or not answers:
        raise ApiError(40001, 400, "answers 必须是非空数组")
    if len(answers) != len(questions):
        raise ApiError(40001, 400, "答案数量与题目数量不一致")

    seen_ids: set = set()
    for item in answers:
        if not isinstance(item, dict):
            raise ApiError(40001, 400, "answers 元素必须是对象")
        answer_id = item.get("id")
        if not isinstance(answer_id, str) or not answer_id.strip():
            raise ApiError(40001, 400, "答案项 id 不能为空")
        if answer_id not in question_ids:
            raise ApiError(40001, 400, f"题目不存在：{answer_id}")
        if answer_id in seen_ids:
            raise ApiError(40001, 400, f"题目 id 重复：{answer_id}")
        seen_ids.add(answer_id)
        q = question_index[answer_id]
        if q["type"] == "choice":
            answer_idx = item.get("answer_idx")
            if not isinstance(answer_idx, int) or isinstance(answer_idx, bool):
                raise ApiError(40001, 400, "answer_idx 必须是整数")
            if not 0 <= answer_idx <= 3:
                raise ApiError(40001, 400, "答案索引超出范围")
        else:  # writing / speaking
            text = item.get("text")
            if (
                not isinstance(text, str)
                or not text.strip()
                or len(text) > 5000
            ):
                raise ApiError(40001, 400, "text 必须是 5000 字以内的非空字符串")
    if seen_ids != question_ids:
        raise ApiError(40001, 400, "答案题目集合与试卷不一致")

    result = exam.grade(paper_id, answers)
    detail = {
        "paper_id": result["paper_id"],
        "exam_type": result["exam_type"],
        "total_score": result["total_score"],
        "max_score": result["max_score"],
        "objective_score": result["objective_score"],
        "subjective_score": result["subjective_score"],
        "level_hint": result["level_hint"],
        "summary_zh": result["summary_zh"],
        "unscored_items": result["unscored_items"],
        "unscored_count": result["unscored_count"],
        "items": result["items"],
    }
    # 允许重复交卷：每次都写一条新的 attempts(kind='exam')，无判重跳过
    db.add_attempt(db.DEFAULT_USER_ID, "exam", result["total_score"], detail)

    # TASK-0055 考级信号（较强 α=0.60）：按试卷 section 聚合得分率映射维度（只算 scored 题）
    _EXAM_SECTION_DIMS = {
        "听力理解": ["listening"],
        "阅读理解": ["reading"],
        "词汇语法": ["vocabulary", "grammar"],
        "观点逻辑": ["reading", "grammar"],
        "书面表达": ["grammar"],
        "口语表达": ["speaking", "fluency"],
    }
    q_section = {q["id"]: q.get("section") for q in questions}
    sec_score: dict = {}
    for it in result["items"]:
        if not it.get("scored"):
            continue
        sec = q_section.get(it["id"])
        if sec not in _EXAM_SECTION_DIMS:
            continue
        agg = sec_score.setdefault(sec, {"s": 0, "m": 0})
        agg["s"] += it["score"]
        agg["m"] += it["max_score"]
    exam_events = []
    for sec, agg in sec_score.items():
        if agg["m"] <= 0:
            continue
        pct = round(agg["s"] / agg["m"] * 100, 1)
        for dim in _EXAM_SECTION_DIMS[sec]:
            exam_events.append((dim, pct, "exam", paper_id))
    _record_skill_events(exam_events)

    return ok(result)


# ---------------------------------------------------------------- 零基础读音规则学习 API（先于静态 mount 声明）
# 契约 PRONUNCIATION_CONTRACT.md v1.0 §3：4 端点；错误码仅 0/40001/40401/50001。

@app.get("/api/pronunciation/rules")
async def pronunciation_rules(group: str | None = None):
    """规则摘要列表（小册子索引）；group 省略/空=不过滤，非空须为 8 个合法组名之一。"""
    if group:
        if group not in pronunciation.GROUPS:
            raise ApiError(40001, 400, f"非法分组：{group}")
    else:
        group = None
    return ok(pronunciation.list_rules(group))


@app.get("/api/pronunciation/rules/{rule_id}")
async def pronunciation_rule_detail(rule_id: str):
    """单条规则完整详情（10 字段）；不存在 → 40401。"""
    detail = pronunciation.get_rule(rule_id)
    if detail is None:
        raise ApiError(40401, 404, f"读音规则不存在：{rule_id}")
    return ok(detail)


@app.get("/api/pronunciation/progress")
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


@app.post("/api/pronunciation/progress")
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
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
else:
    logger.warning(
        "frontend 目录不存在（%s），跳过静态托管；API 仍可正常访问。", FRONTEND_DIR
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("YAYA_BACKEND_PORT", "8000")))
