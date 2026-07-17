"""专用浏览器配置与 Chrome DevTools 网络监听。"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from websocket import WebSocket, WebSocketException, WebSocketTimeoutException, create_connection

from .paths import BROWSER_PROFILE_DIR, ensure_data_dirs


SITE_URL = "https://jw.ruc.edu.cn/Njw2017/index.html#/"


def locate_browser() -> str:
    system = platform.system()
    candidates = {
        "Darwin": [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ],
        "Windows": [
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
        ],
        "Linux": ["google-chrome", "google-chrome-stable", "microsoft-edge", "chromium"],
    }.get(system, [])
    for candidate in candidates:
        resolved = shutil.which(candidate) or candidate
        if Path(resolved).is_file():
            return resolved
    raise FileNotFoundError("未找到 Chrome 或 Edge，请先安装其中一个浏览器。")


@dataclass
class BrowserSession:
    process: subprocess.Popen[Any]
    debugger_port: int

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


def launch_browser(url: str = SITE_URL) -> BrowserSession:
    """启动复用 .data/browser-profile 的独立浏览器窗口。"""
    ensure_data_dirs()
    active_port = BROWSER_PROFILE_DIR / "DevToolsActivePort"
    # 避免上次异常退出时遗留的端口文件被误认为新浏览器。
    active_port.unlink(missing_ok=True)
    process = subprocess.Popen(
        [
            locate_browser(),
            "--remote-debugging-port=0",
            "--remote-allow-origins=*",
            f"--user-data-dir={BROWSER_PROFILE_DIR}",
            "--new-window",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-notifications",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            error = process.stderr.read().decode("utf-8", errors="replace").strip()
            detail = f"：{error}" if error else ""
            raise RuntimeError(f"浏览器启动进程已退出{detail}")
        if active_port.exists():
            try:
                port = int(active_port.read_text(encoding="utf-8").splitlines()[0])
                with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2):
                    return BrowserSession(process, port)
            except (OSError, ValueError, IndexError):
                pass
        time.sleep(0.2)
    process.terminate()
    raise TimeoutError("浏览器启动后无法连接本机 DevTools。")


class NetworkMonitor:
    """监听同一浏览器中所有页面，捕获请求但不落盘原始认证头。"""

    def __init__(self, debugger_port: int) -> None:
        self.debugger_port = debugger_port
        self.requests: list[dict[str, Any]] = []
        self._connections: dict[str, WebSocket] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._discover_pages()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)
        for connection in self._connections.values():
            connection.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._discover_pages()
            for endpoint, connection in list(self._connections.items()):
                self._drain(endpoint, connection)
            self._stop.wait(0.2)

    def _discover_pages(self) -> None:
        try:
            with urlopen(f"http://127.0.0.1:{self.debugger_port}/json/list", timeout=2) as response:
                pages = json.load(response)
        except (OSError, json.JSONDecodeError):
            return
        active = {
            item["webSocketDebuggerUrl"]
            for item in pages
            if item.get("type") == "page" and item.get("webSocketDebuggerUrl")
        }
        for endpoint in active - self._connections.keys():
            try:
                connection = create_connection(endpoint, timeout=1)
                connection.settimeout(0.05)
                connection.send(json.dumps({"id": 1, "method": "Network.enable"}))
                self._connections[endpoint] = connection
            except (OSError, WebSocketException):
                continue
        for endpoint in self._connections.keys() - active:
            self._connections.pop(endpoint).close()

    def _drain(self, endpoint: str, connection: WebSocket) -> None:
        while not self._stop.is_set():
            try:
                message = json.loads(connection.recv())
            except (TimeoutError, WebSocketTimeoutException):
                return
            except (OSError, WebSocketException, json.JSONDecodeError):
                self._connections.pop(endpoint, None)
                return
            if message.get("method") != "Network.requestWillBeSent":
                continue
            request = message["params"]["request"]
            self.requests.append(
                {
                    "url": request["url"],
                    "method": request["method"],
                    "body": request.get("postData"),
                }
            )
