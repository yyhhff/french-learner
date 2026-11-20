"""v3.3 语法微卡路由：卡库下发 + 错误画像（TASK-0078）。

引擎在 backend/grammar.py，本文件只做装配与参数收口；零写端点（画像由
chat 挂接自动落库，不开放人工写入口）。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

import db
import grammar as grammar_engine
from common import ok

logger = logging.getLogger("yaya.grammar")

router = APIRouter()


@router.get("/api/grammar/cards")
async def grammar_cards():
    """全量卡库（含 patterns，前端本地句扫描用；卡片 ≤50 张、纯静态内容）。"""
    cards = grammar_engine.load_cards()
    problems = grammar_engine.validate_cards(cards)
    if problems:
        # 库本身有问题只记日志不下发错误——面客永远拿到可渲染的子集
        logger.warning("语法卡库 schema 异常（下发不受阻）：%s", problems[:5])
    return ok({
        "items": [grammar_engine.card_public(c) for c in cards],
        "total": len(cards),
    })


@router.get("/api/grammar/profile")
async def grammar_profile():
    """错误画像 + 同类 ≥3 次的建议卡（review 页 banner / 今日提示消费）。"""
    return ok(grammar_engine.profile(db.DEFAULT_USER_ID))
