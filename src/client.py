"""选课协议适配接口与请求频率控制。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol

from .models import Availability, CourseTarget, SubmitResult


@dataclass(frozen=True)
class AvailabilityResult:
    status: Availability
    message: str = ""


@dataclass(frozen=True)
class SubmissionResult:
    status: SubmitResult
    message: str = ""


class CourseClient(Protocol):
    async def availability(self, target: CourseTarget) -> AvailabilityResult: ...

    async def submit(self, target: CourseTarget) -> SubmissionResult: ...


class RequestLimiter:
    """全局最小请求间隔；所有课程任务共享同一个实例。"""

    def __init__(self, requests_per_second: int) -> None:
        self._interval = 1 / requests_per_second
        self._next_allowed = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + self._interval
        if delay:
            await asyncio.sleep(delay)


class UnconfiguredCourseClient:
    """在余量响应协议确认前阻止真实 HTTP 请求的安全默认实现。"""

    async def availability(self, target: CourseTarget) -> AvailabilityResult:
        return AvailabilityResult(
            Availability.UNKNOWN,
            "尚未配置余量响应解析器；不会对教务系统发起自动请求。",
        )

    async def submit(self, target: CourseTarget) -> SubmissionResult:
        return SubmissionResult(SubmitResult.UNKNOWN, "提交适配器尚未配置。")
