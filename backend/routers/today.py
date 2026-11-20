"""v3.0 今日路由（TASK-0070）：GET /api/today 聚合今日三件事 + XP/等级 + streak + 呀呀态。

新端点一律写独立 router（MASTER_PLAN §4 文件边界）。只读聚合 + gamify 明细，
不新增写路径。
"""
from fastapi import APIRouter

import gamify
from common import ok

router = APIRouter()


@router.get("/api/today")
async def today():
    """今日首页数据体：任务三件事（复习/阅读/对话）+ XP/等级 + streak + 呀呀陪伴态。

    全部实时聚合既有表（gamify.today_summary 内逐块降级），无状态任务表。
    """
    return ok(gamify.today_summary())
