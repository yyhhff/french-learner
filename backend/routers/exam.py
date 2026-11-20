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


# ---------------------------------------------------------------- 阶段4 考级冲刺 API（先于静态 mount 声明）
# 契约 ARCHITECTURE_EXAM.md v1.0 §3：列表不含题目、详情白名单脱敏、交卷每次写一条 records。

@router.get("/api/exam/papers")
async def exam_papers():
    """试卷列表（PaperSummary[]）；缓存空降级 []，不抛 500。"""
    return ok(exam.list_papers())


@router.get("/api/exam/papers/{paper_id}")
async def exam_paper_detail(paper_id: str):
    """试卷详情公开视图；不存在 → 40401。"""
    detail = exam.get_public_paper(paper_id)
    if detail is None:
        raise ApiError(40401, 404, "试卷不存在，换一套试试～")
    return ok(detail)


@router.post("/api/exam/submit")
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

