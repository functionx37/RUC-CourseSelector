"""受限并发的选课运行器。"""

from __future__ import annotations

import asyncio
import logging

from .client import CourseClient, RequestLimiter
from .models import Availability, CourseTarget, RunConfig, SubmitResult
from .schedule import is_active, seconds_until_active
from .targets import TargetStore


class CourseRunner:
    def __init__(
        self,
        client: CourseClient,
        store: TargetStore,
        config: RunConfig = RunConfig(),
        logger: logging.Logger | None = None,
    ) -> None:
        self.client = client
        self.store = store
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.stop_event = asyncio.Event()
        self.limiter = RequestLimiter(config.global_requests_per_second)

    async def run(self, targets: list[CourseTarget]) -> None:
        active_targets = targets[: self.config.max_courses]
        if len(targets) > len(active_targets):
            self.logger.warning("目标课程超过上限，仅运行前 %s 门。", self.config.max_courses)
        tasks = [asyncio.create_task(self._run_target(target)) for target in active_targets]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            self.stop_event.set()
            raise

    async def _run_target(self, target: CourseTarget) -> None:
        submits = 0
        while not self.stop_event.is_set():
            if not is_active():
                await self._wait_or_stop(seconds_until_active())
                continue

            await self.limiter.wait()
            availability = await self.client.availability(target)
            if availability.status is Availability.UNAVAILABLE:
                await self._wait_or_stop(self.config.query_interval_seconds)
                continue
            if availability.status is Availability.SESSION_EXPIRED:
                self.logger.error("%s：会话已失效，停止。", target.class_name)
                return
            if availability.status is Availability.UNKNOWN:
                self.logger.warning("%s：%s", target.class_name, availability.message)
                return

            if submits >= self.config.max_submit_attempts:
                self.logger.info("%s：达到本窗口提交上限，停止该课程。", target.class_name)
                return

            await self.limiter.wait()
            submits += 1
            result = await self.client.submit(target)
            if result.status is SubmitResult.SUCCESS:
                self.store.remove_key(target.key)
                self.logger.info("%s：选课成功，已从目标列表移除。", target.class_name)
                return
            if result.status in (SubmitResult.ALREADY_SELECTED, SubmitResult.CATEGORY_LIMIT):
                self.store.remove_key(target.key)
                self.logger.info("%s：%s，已从目标列表移除。", target.class_name, result.message)
                return
            if result.status is SubmitResult.SESSION_EXPIRED:
                self.logger.error("%s：会话已失效，停止。", target.class_name)
                return
            if result.status is SubmitResult.NO_CAPACITY:
                await self._wait_or_stop(self.config.query_interval_seconds)
                continue
            if result.status is SubmitResult.BUSY:
                await self._wait_or_stop(self.config.busy_backoff_seconds)
                continue
            self.logger.warning("%s：%s", target.class_name, result.message or "未知提交响应")
            return

    async def _wait_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)
        except TimeoutError:
            return
