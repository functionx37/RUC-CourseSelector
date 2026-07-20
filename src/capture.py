"""通过用户手动操作采集完整的目标课程提交体。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

from .browser import SITE_URL, NetworkMonitor, launch_browser
from .models import CourseTarget
from .query_session import QuerySession, QueryTemplate


SAVE_ENDPOINT = "/stuCourseCenterController/saveStuXkByRmdx"
LIST_ENDPOINT = "/stuCourseCenterController/findKcInfoByflByRmdx"


@dataclass(frozen=True)
class CaptureResult:
    targets: list[CourseTarget]
    query_session: QuerySession


def collect_targets(prompt: Callable[[str], str] = input) -> CaptureResult:
    """采集目标课程、课程列表请求模板和当前浏览器会话头。"""
    session = launch_browser(SITE_URL)
    monitor = NetworkMonitor(session.debugger_port, capture_headers=True)
    monitor.start()
    print("请在浏览器进入选课页面，对目标课程点击一次选课。")
    print("余量不足、已选或成功均可；请先打开目标课程所属分类以采集余量查询模板。")
    print("完成后回到此处按 Enter。")
    try:
        prompt("")
        # 让最后一次点击触发的请求和附加认证头到达 DevTools 监听器。
        time.sleep(1)
    finally:
        monitor.stop()
        session.close()

    targets: list[CourseTarget] = []
    seen: set[str] = set()
    for request in monitor.requests:
        if request["method"] != "POST" or SAVE_ENDPOINT not in request["url"]:
            continue
        try:
            payload = json.loads(request["body"] or "")
            target = CourseTarget.from_payload(payload)
        except (json.JSONDecodeError, ValueError):
            continue
        if target.key not in seen:
            targets.append(target)
            seen.add(target.key)
    return CaptureResult(targets, QuerySession(_query_templates(monitor.requests)))


def _query_templates(requests: list[dict[str, object]]) -> dict[str, QueryTemplate]:
    """保留各课程分类最近一次真实列表查询；请求头包含当前会话凭据。"""
    templates: dict[str, QueryTemplate] = {}
    for request in requests:
        if request.get("method") != "POST" or LIST_ENDPOINT not in str(request.get("url")):
            continue
        try:
            payload = json.loads(str(request.get("body") or ""))
        except json.JSONDecodeError:
            continue
        category = payload.get("kclbCodeMapper") if isinstance(payload, dict) else None
        headers = request.get("headers")
        if category is None or not isinstance(headers, dict):
            continue
        templates[str(category)] = QueryTemplate(
            url=str(request["url"]),
            body=str(request["body"]),
            headers={str(name): str(value) for name, value in headers.items()},
        )
    return templates
