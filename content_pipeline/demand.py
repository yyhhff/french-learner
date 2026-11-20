"""需求矩阵：主题 × 场景 × 等级 → 需求队列。

每个需求槽位（slot）是一条「生成任务单」：目标等级、主题、场景、体裁、目标句数。
队列落 data/cache/content_pipeline/demand_queue.json，生成阶段逐个消费。
去重键 = (level, topic, scene, format)，保证不重复生产同一题材。
"""
from __future__ import annotations

import json

from content_pipeline.paths import (
    CACHE_DIR,
    DEMAND_FILE,
    PER_LEVEL_TARGET,
    TARGET_LEVELS,
    ensure_dirs,
)

# 主题（贴近现有 9 类，去掉重复语义）+ 每主题的典型场景
# 场景是可组合的微情境，确保同一主题下能产出多篇不重复语料。
TOPIC_SCENES: dict[str, list[str]] = {
    "日常": ["早晨起床", "超市购物", "在面包店", "邻里寒暄", "周末计划", "天气闲聊", "借东西", "预约理发"],
    "出行": ["问路", "坐地铁", "买火车票", "机场值机", "打车", "租车", "公交换乘", "问时刻表"],
    "购物": ["试衣服", "退换货", "菜市场", "书店", "砍价", "网上订单", "付账方式", "找零钱"],
    "健康": ["看医生", "药店买药", "描述症状", "体检预约", "健身房", "牙医", "情绪倾诉", "健康饮食"],
    "工作": ["自我介绍", "面试", "请假", "开会发言", "同事闲聊", "接电话", "写邮件措辞", "下班道别"],
    "生活": ["租房", "搬家", "修东西", "水电缴费", "邻居纠纷", "宠物", "做饭", "快递收发"],
    "文化": ["看电影", "博物馆", "读书", "音乐偏好", "节日", "婚礼", "展览", "地道小吃"],
    "媒体": ["看新闻", "刷社交媒体", "听广播", "追剧", "天气预报", "体育赛事", "广告", "网络用语"],
    "社会": ["环保", "交通安全", "社区活动", "志愿服务", "校园生活", "代际沟通", "城市变化", "公共礼仪"],
}

FORMATS = ("dialogue", "monologue")
# 各等级目标句数区间（校验器据此判断句长/篇幅漂移）
LEVEL_SENTENCES = {"A1": (3, 5), "A2": (4, 6), "B1": (5, 8), "B2": (6, 10)}


def _level_format_for_index(i: int) -> str:
    """对话与独白交替，避免某等级全是对话。"""
    return FORMATS[i % len(FORMATS)]


def build_queue(per_level: int = PER_LEVEL_TARGET, levels: tuple[str, ...] = TARGET_LEVELS) -> dict:
    """构建需求队列；按 level 轮转 topic×scene，体裁交替，直到每等级达标。

    返回结构：{version, per_level_target, slots:[{id,level,topic,scene,format,target_sentences}], ...}
    """
    topics = list(TOPIC_SCENES)
    slot_keys: set[tuple[str, str, str, str]] = set()
    slots: list[dict] = []

    for level in levels:
        made = 0
        ti = 0
        # 轮转所有 (topic, scene) 组合，体裁交替；不足则第二轮换体裁再补
        combos = [(t, s) for t in topics for s in TOPIC_SCENES[t]]
        while made < per_level:
            for t, s in combos:
                if made >= per_level:
                    break
                fmt = _level_format_for_index(made)
                key = (level, t, s, fmt)
                if key in slot_keys:
                    continue
                slot_keys.add(key)
                lo, hi = LEVEL_SENTENCES[level]
                slots.append(
                    {
                        "id": f"dem_{level.lower()}_{made + 1:03d}",
                        "level": level,
                        "topic": t,
                        "scene": s,
                        "format": fmt,
                        "target_sentences": [lo, hi],
                    }
                )
                made += 1
                ti += 1
            # 若一轮不够（组合数 > per_level 时不会发生），保险起见防死循环
            if not combos:
                break

    return {
        "version": 1,
        "per_level_target": per_level,
        "levels": list(levels),
        "total": len(slots),
        "slots": slots,
    }


def load_queue() -> dict | None:
    if not DEMAND_FILE.is_file():
        return None
    try:
        return json.loads(DEMAND_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_queue(queue: dict) -> None:
    ensure_dirs()
    DEMAND_FILE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")


def build_and_save(per_level: int = PER_LEVEL_TARGET) -> dict:
    queue = build_queue(per_level)
    save_queue(queue)
    return queue


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="构建 v2.3 语料需求队列")
    ap.add_argument("--per-level", type=int, default=PER_LEVEL_TARGET)
    args = ap.parse_args()
    q = build_and_save(args.per_level)
    print(f"需求队列已生成：{q['total']} 槽位 → {DEMAND_FILE}")
    from collections import Counter

    print("按等级：", dict(Counter(s["level"] for s in q["slots"])))
