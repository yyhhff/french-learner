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


@router.get("/api/tts")
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

