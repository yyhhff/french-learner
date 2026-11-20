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


@router.get("/api/roadmap")
async def roadmap():
    """TASK-0059 面客建设里程图：服务端常量下发，前端只读渲染。

    维护点唯一：改 ROADMAP_DEFS 的 status/date 即点亮，前端零改动。
    """
    done = [r for r in ROADMAP_DEFS if r["status"] == "done"]
    return ok({
        "items": ROADMAP_DEFS,
        "current_version": next(
            (r["version"] for r in ROADMAP_DEFS if r["status"] == "active"),
            (done[-1]["version"] if done else ROADMAP_DEFS[0]["version"]),
        ),
        "done_count": len(done),
        "total": len(ROADMAP_DEFS),
    })

