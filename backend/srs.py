"""SM-2 简化版复习调度（契约 7.2）。

对外接口固定：schedule(rating, state) -> (new_state, next_due, interval_days)
- state = {repetitions, ease_factor, interval_days}，初始 (0, 2.5, 0)
- rating ∈ {1,2,3,4}（由 API 层校验）
- next_due 为 ISO8601 日期时间（UTC + Z），interval_days 为整数
替换成 FSRS 时只改本文件，API 契约不变。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def schedule(rating: int, state: dict) -> tuple[dict, str, int]:
    repetitions = int(state["repetitions"])
    ease_factor = float(state["ease_factor"])
    prev_interval = int(state["interval_days"])

    if rating >= 3:  # 记得
        repetitions += 1
        if repetitions == 1:
            interval = 1
        elif repetitions == 2:
            interval = 6
        else:
            interval = round(prev_interval * ease_factor)
    else:  # 忘记
        repetitions = 0
        interval = 1

    q = rating
    ease_factor = max(
        1.3, ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    )

    next_due = (
        datetime.now(timezone.utc) + timedelta(days=interval)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    new_state = {
        "repetitions": repetitions,
        "ease_factor": ease_factor,
        "interval_days": interval,
    }
    return new_state, next_due, interval
