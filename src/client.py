"""选课协议适配接口与请求频率控制。"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import Availability, CourseTarget, SubmitResult
from .query_session import QuerySession, QueryTemplate


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


class BrowserSessionCourseClient:
    """使用 choose 时捕获的浏览器会话，读取课程列表中的实时余量。"""

    _MANAGED_HEADERS = {"accept-encoding", "connection", "content-length", "host"}

    def __init__(self, query_session: QuerySession) -> None:
        self.query_session = query_session

    async def availability(self, target: CourseTarget) -> AvailabilityResult:
        template = self.query_session.template_for(target)
        if template is None:
            return AvailabilityResult(
                Availability.UNKNOWN,
                "未捕获该课程分类的余量查询模板；请重新执行 choose 并打开对应分类。",
            )
        try:
            status, body = await asyncio.to_thread(self._post, template)
        except (RuntimeError, ValueError) as error:
            return AvailabilityResult(Availability.UNKNOWN, str(error))
        if status in (401, 403):
            return AvailabilityResult(Availability.SESSION_EXPIRED, f"HTTP {status}")
        if status != 200:
            return AvailabilityResult(Availability.UNKNOWN, f"余量查询返回 HTTP {status}")
        try:
            response = json.loads(body)
        except json.JSONDecodeError:
            if _looks_like_login_page(body):
                return AvailabilityResult(Availability.SESSION_EXPIRED, "查询被重定向至登录页面。")
            return AvailabilityResult(Availability.UNKNOWN, "余量查询响应不是 JSON。")
        if not isinstance(response, dict):
            return AvailabilityResult(Availability.UNKNOWN, "余量查询响应格式异常。")
        error_code = str(response.get("errorCode") or "")
        message = str(response.get("errorMessage") or error_code)
        if error_code != "success":
            if _looks_like_session_error(error_code, message):
                return AvailabilityResult(Availability.SESSION_EXPIRED, message)
            return AvailabilityResult(Availability.UNKNOWN, f"余量查询失败：{message}")
        course = _matching_course(response, target)
        if course is None:
            return AvailabilityResult(Availability.UNKNOWN, "当前课程列表未找到目标教学班。")
        selected = _number(course.get("xkrs"))
        maximum = _number(course.get("xxrs"))
        if selected is None or maximum is None:
            return AvailabilityResult(Availability.UNKNOWN, "响应未包含有效的 xkrs/xxrs。")
        message = f"已选/最大：{selected:g}/{maximum:g}"
        status = Availability.AVAILABLE if maximum > selected else Availability.UNAVAILABLE
        return AvailabilityResult(status, message)

    async def submit(self, target: CourseTarget) -> SubmissionResult:
        template = self.query_session.submit_template
        if template is None:
            return SubmissionResult(
                SubmitResult.UNKNOWN,
                "未捕获选课提交模板；请重新执行 choose 并手动点击目标课程。",
            )
        body = json.dumps(target.payload, ensure_ascii=False, separators=(",", ":"))
        try:
            status, response_body = await asyncio.to_thread(self._post, template, body)
        except (RuntimeError, ValueError) as error:
            return SubmissionResult(SubmitResult.UNKNOWN, str(error))
        if status in (401, 403):
            return SubmissionResult(SubmitResult.SESSION_EXPIRED, f"HTTP {status}")
        if status != 200:
            return SubmissionResult(SubmitResult.UNKNOWN, f"选课提交返回 HTTP {status}")
        try:
            response = json.loads(response_body)
        except json.JSONDecodeError:
            if _looks_like_login_page(response_body):
                return SubmissionResult(SubmitResult.SESSION_EXPIRED, "提交被重定向至登录页面。")
            return SubmissionResult(SubmitResult.UNKNOWN, "选课提交响应不是 JSON。")
        if not isinstance(response, dict):
            return SubmissionResult(SubmitResult.UNKNOWN, "选课提交响应格式异常。")
        error_code = str(response.get("errorCode") or "")
        message = str(response.get("errorMessage") or error_code)
        if error_code == "success":
            return SubmissionResult(SubmitResult.SUCCESS, message)
        if error_code == "eywxt.save.cantXkByCopy.error":
            return SubmissionResult(SubmitResult.ALREADY_SELECTED, message)
        if _looks_like_session_error(error_code, message):
            return SubmissionResult(SubmitResult.SESSION_EXPIRED, message)
        return SubmissionResult(SubmitResult.UNKNOWN, f"选课提交失败：{message}")

    def _post(self, template: QueryTemplate, body: str | None = None) -> tuple[int, str]:
        headers = {
            name: value
            for name, value in template.headers.items()
            if name.lower() not in self._MANAGED_HEADERS
        }
        # 避免 urllib 收到浏览器协商的压缩响应后无法自动解压。
        headers["Accept-Encoding"] = "identity"
        request = Request(
            template.url,
            data=(template.body if body is None else body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                return response.status, response.read().decode("utf-8", errors="replace")
        except HTTPError as error:
            return error.code, error.read().decode("utf-8", errors="replace")
        except URLError as error:
            raise RuntimeError(f"无法连接教务系统：{error.reason}") from error


def _matching_course(response: dict[str, object], target: CourseTarget) -> dict[str, object] | None:
    data = response.get("data")
    if not isinstance(data, dict):
        return None
    courses = data.get("showKclist")
    if not isinstance(courses, list):
        return None
    target_ids = {
        str(value)
        for value in (
            target.teaching_class_id,
            target.payload.get("id"),
            target.payload.get("kkgl004id"),
            target.payload.get("kth"),
        )
        if value is not None and str(value)
    }
    for course in courses:
        if not isinstance(course, dict):
            continue
        if any(
            str(course.get(field)) in target_ids
            for field in ("id", "kkgl004id", "kth")
            if course.get(field) is not None
        ):
            return course
    return None


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _looks_like_login_page(body: str) -> bool:
    normalized = body.lower()
    return "oauthlogin" in normalized or "cas.ruc.edu.cn" in normalized


def _looks_like_session_error(error_code: str, message: str) -> bool:
    normalized = f"{error_code} {message}".lower()
    return any(term in normalized for term in ("token", "session", "登录", "未登录", "login"))
