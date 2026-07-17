"""选课运行时间窗。"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


def is_active(now: datetime | None = None) -> bool:
    current = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    if not 7 <= current.hour < 23:
        return False
    seconds_in_hour = current.minute * 60 + current.second
    offset = seconds_in_hour % 300
    return offset <= 30 or offset >= 270


def seconds_until_active(now: datetime | None = None) -> float:
    current = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    if is_active(current):
        return 0.0
    probe = current.replace(microsecond=0)
    # 最长只扫描至下一天 07:00；以秒级精度实现简单且容易验证。
    for seconds in range(1, 24 * 60 * 60 + 1):
        candidate = probe + timedelta(seconds=seconds)
        if is_active(candidate):
            return float(seconds)
    raise RuntimeError("无法找到下一个选课时间窗。")
