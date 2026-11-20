"""Wave 0 共享件：从原 app.py 原样搬出，供各 router 复用，避免循环依赖。"""
import json
import logging
import os
import re
import string
import urllib.request

from fastapi import Request
from fastapi.responses import JSONResponse

import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yaya.app")

# ---------------------------------------------------------------- TASK-0059 面客建设里程图
# 唯一维护点：每个大版本一个完整主题闭环；status done/active/planned。
# 点亮新版本 = 把对应条目的 status 改为 done、填 date；无需改前端或数据库。
# 维护说明见 docs/ROADMAP.md。改动需重启服务生效（无热加载）。
ROADMAP_DEFS = [
    {
        "version": "v1.0", "title": "会说话的开始", "theme": "重述式口语陪练",
        "status": "done", "date": "2026-11-17",
        "desc": "像婴儿一样开口——说错了不挨骂，我顺着你的话把对的讲法轻轻讲给你。",
        "features": ["4 个生活场景对话", "重述式纠错（不打回）", "生词卡 + SM-2 复习", "逐句发音与中文小字"],
    },
    {
        "version": "v1.1", "title": "把音读准", "theme": "零基础读音规则",
        "status": "done", "date": "2026-11-19",
        "desc": "点一个词就看它怎么读、为什么这样读，还能跟着念一遍。",
        "features": ["39 条读音规则", "逐词气泡 + 连读教学", "🎙 跟读近似比对", "词卡发音覆盖 97.8%"],
    },
    {
        "version": "v1.2", "title": "读得下去", "theme": "i+1 分级输入与成长",
        "status": "done", "date": "2026-11-19",
        "desc": "读得懂又学得到的短文，读完留个小脚印，回头看得见自己。",
        "features": ["A2/B1/B2 分级阅读", "逐词发音 + 连读", "进度持久化", "我的成长视图"],
    },
    {
        "version": "v1.3", "title": "温柔地记得", "theme": "学习闭环激励",
        "status": "done", "date": "2026-11-20",
        "desc": "该见的词自己回来，每一步都有小小回应——不催、不扣分。",
        "features": ["SM-2 到期调度", "成就点亮", "五维水平画像", "3 步新手引导"],
    },
    {
        "version": "v2.0", "title": "知道自己在哪儿", "theme": "CEFR 定级与考级",
        "status": "done", "date": "2026-11-18",
        "desc": "先认清当下的位置，再朝着目标稳稳走——原创题目，随时可练。",
        "features": ["12 题 CEFR 定级", "DELF B2 / TCF 模拟卷", "服务端判分零泄露"],
    },
    {
        "version": "v2.1", "title": "明天还想来", "theme": "留存深化",
        "status": "done", "date": "2026-11-20",
        "desc": "一点小目标、一句「接着上次」，让学习像每天散个步一样自然。",
        "features": ["今日小目标", "接着上次", "成长趋势"],
    },
    # ---------------- TASK-0063 补强总纲 v2.2–v4.1（planned 灰态；详案与认领看板见 docs/MASTER_PLAN.md）
    {
        "version": "v2.2", "title": "第一级台阶", "theme": "零基础 A1 通路",
        "status": "done", "date": "2026-11-20",
        "desc": "从读音到第一句，零基础也有刚刚好的台阶。",
        "features": ["A1 定级档（四档 24 题）与新手台阶路径", "高频词 + 基础句型", "A1 分级语料 10 篇与对话场景"],
    },
    {
        "version": "v2.3", "title": "读不完的书", "theme": "内容量产管线",
        "status": "planned", "date": None,
        "desc": "分级短文源源不断，总有刚好适合你的下一篇。",
        "features": ["语料生成与难度校验管线", "200+ 篇 A1–B2 分级内容", "音频批量预生成"],
    },
    {
        "version": "v3.0", "title": "每天十五分钟", "theme": "每日路径与游戏化",
        "status": "planned", "date": None,
        "desc": "打开就知道今天学什么，一点小积累看得见。",
        "features": ["今日任务视图", "经验与等级", "连续天数（温和记录不惩罚）", "呀呀陪伴成长"],
    },
    {
        "version": "v3.1", "title": "耳朵开口", "theme": "听力强化",
        "status": "planned", "date": None,
        "desc": "慢慢听、逐句听，直到耳朵跟得上真实语速。",
        "features": ["变速听力", "精听听写填空", "口语缩略与多音色语速变体"],
    },
    {
        "version": "v3.2", "title": "发音教练", "theme": "跟读打分",
        "status": "planned", "date": None,
        "desc": "跟着念一遍，哪儿没发出来温柔告诉你。",
        "features": ["跟读录音三维评分", "词级命中反馈", "发音挑战任务"],
    },
    {
        "version": "v3.3", "title": "语法的针脚", "theme": "显性语法微卡",
        "status": "planned", "date": None,
        "desc": "遇到时轻轻点一下，语法就缝进了句子里。",
        "features": ["40+ 语法微卡", "阅读情境嵌入", "按重述错误推荐"],
    },
    {
        "version": "v4.0", "title": "说得出口", "theme": "口语四维测评",
        "status": "planned", "date": None,
        "desc": "用你说过的每一句话，画一张口语体检报告。",
        "features": ["流利/准确/复杂/互动四维报告", "自适应定级", "定期重测提醒"],
    },
    {
        "version": "v4.1", "title": "口袋里的呀呀", "theme": "移动与部署",
        "status": "planned", "date": None,
        "desc": "通勤排队都能学，呀呀装进口袋。",
        "features": ["手机响应式 + PWA", "一键启动简化", "局域网访问"],
    },
]

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

def _record_skill_events(events: list) -> None:
    """TASK-0055：画像事件只写流水不更新画像（懒计算）；失败不阻塞主流程。"""
    try:
        db.record_skill_events(db.DEFAULT_USER_ID, events)
    except Exception:  # noqa: BLE001 — 画像是增益功能，任何异常都不影响提交本身
        pass

# ---------------------------------------------------------------- 本地 ASR 代理

ASR_SERVICE_URL = os.environ.get(
    "YAYA_ASR_URL", "http://127.0.0.1:8011"
).rstrip("/")

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

__all__ = [
    "logger",
    "ROADMAP_DEFS",
    "ApiError",
    "ok",
    "json_body",
    "normalize_user_text",
    "_parse_multipart",
    "_record_skill_events",
    "ASR_SERVICE_URL",
    "_parse_int_param",
    "_optional_json_body",
]
