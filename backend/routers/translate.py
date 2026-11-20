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


@router.post("/api/translate")
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

