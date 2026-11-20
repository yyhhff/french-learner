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


# ---------------------------------------------------------------- 本地 ASR 代理

ASR_SERVICE_URL = os.environ.get(
    "YAYA_ASR_URL", "http://127.0.0.1:8011"
).rstrip("/")


@router.get("/api/asr/status")
async def asr_status():
    """前端启动时探测本地 ASR 服务是否可用，决定是否显示麦克风。"""
    try:
        with urllib.request.urlopen(ASR_SERVICE_URL + "/health", timeout=2) as resp:
            import json

            info = json.loads(resp.read().decode("utf-8"))
        return ok({"available": True, **info})
    except Exception:  # noqa: BLE001 - 服务未起是正常状态
        return ok({"available": False})

@router.post("/api/asr/transcribe")
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

