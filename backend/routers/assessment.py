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


# ---------------------------------------------------------------- 阶段0 定级 API（先于静态 mount 声明）
# 契约 ARCHITECTURE_PLACEMENT.md v1.1 §3：取卷隐藏答案；交卷按 id 判分 + 幂等写回。

@router.get("/api/assessment/questions")
async def assessment_questions():
    """取卷：公开视图 5 字段，绝不下发 answer_idx / explanation_zh。"""
    public = assessment.public_questions(assessment.load_questions())
    return ok({"questions": public, "total": len(public)})


@router.post("/api/assessment/submit")
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

