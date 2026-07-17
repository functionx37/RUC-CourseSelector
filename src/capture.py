"""通过用户手动操作采集完整的目标课程提交体。"""

from __future__ import annotations

import json
from typing import Callable

from .browser import SITE_URL, NetworkMonitor, launch_browser
from .models import CourseTarget


SAVE_ENDPOINT = "/stuCourseCenterController/saveStuXkByRmdx"


def collect_targets(prompt: Callable[[str], str] = input) -> list[CourseTarget]:
    """启动专用浏览器，让用户手动尝试课程后提取提交请求。"""
    session = launch_browser(SITE_URL)
    monitor = NetworkMonitor(session.debugger_port)
    monitor.start()
    print("请在浏览器进入选课页面，对目标课程点击一次选课。")
    print("余量不足、已选或成功均可；完成后回到此处按 Enter。")
    try:
        prompt("")
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
    return targets
