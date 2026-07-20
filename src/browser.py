"""专用浏览器配置与 Chrome DevTools 网络监听。"""

from __future__ import annotations

import json
import os
import platform
import shutil
import signal
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


def _is_wsl() -> bool:
    """判断当前 Linux 进程是否运行在 WSL 中。"""
    if platform.system() != "Linux":
        return False
    try:
        kernel_release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8")
    except OSError:
        kernel_release = ""
    return bool(os.environ.get("WSL_DISTRO_NAME")) or "microsoft" in kernel_release.lower()


def _windows_path_to_wsl_path(windows_path: str) -> Path:
    """将 Windows 路径转换为 WSL 可访问的挂载路径。"""
    try:
        result = subprocess.run(
            ["wslpath", "-u", windows_path],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError("无法将 Windows 路径转换为 WSL 路径。") from error
    converted = result.stdout.strip()
    if not converted:
        raise RuntimeError("无法读取 Windows 路径。")
    return Path(converted)


def _wsl_local_app_data() -> Path:
    """返回 Windows 宿主机可读写的 LocalAppData 路径。"""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        try:
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "echo", "%LOCALAPPDATA%"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise RuntimeError("无法读取 Windows 的 LOCALAPPDATA；请确认 WSL 互操作已启用。") from error
        local_app_data = result.stdout.strip()
    if not local_app_data or local_app_data == "%LOCALAPPDATA%":
        raise RuntimeError("Windows 的 LOCALAPPDATA 未设置，无法为浏览器创建专用配置。")
    return _windows_path_to_wsl_path(local_app_data)


def browser_profile_dir() -> Path:
    """返回当前浏览器可读写的专用配置目录。"""
    if _is_wsl():
        # Windows 浏览器未必有权限访问 /mnt 下的项目目录，因此不能复用项目内 .data。
        return _wsl_local_app_data() / "RUC-CourseSelector" / "browser-profile"
    return BROWSER_PROFILE_DIR


def locate_browser() -> str:
    system = platform.system()
    if _is_wsl():
        local_app_data = _wsl_local_app_data()
        candidates = [
            "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
            "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
            local_app_data / "Google/Chrome/Application/chrome.exe",
            "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
            "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            local_app_data / "Microsoft/Edge/Application/msedge.exe",
        ]
    else:
        candidates = {
            "Darwin": [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            ],
            "Windows": [
                os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
                os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
            ],
            "Linux": [
                "google-chrome",
                "google-chrome-stable",
                "microsoft-edge",
                "microsoft-edge-stable",
                "chromium",
                "chromium-browser",
            ],
        }.get(system, [])
    for candidate in candidates:
        resolved = shutil.which(str(candidate)) or str(candidate)
        if Path(resolved).is_file():
            return resolved
    if _is_wsl():
        raise FileNotFoundError("未找到 Windows 宿主机上的 Chrome 或 Edge，请先安装其中一个浏览器。")
    raise FileNotFoundError("未找到 Chrome 或 Edge，请先安装其中一个浏览器。")


@dataclass
class BrowserSession:
    process: subprocess.Popen[Any]
    debugger_port: int

    def close(self) -> None:
        """关闭本次启动的浏览器及其全部子进程。"""
        if self.process.poll() is not None:
            return
        if platform.system() == "Windows" or _is_wsl():
            try:
                # Windows Chrome/Edge 会派生多个进程；仅结束父进程可能留下窗口。
                subprocess.run(
                    ["taskkill.exe", "/PID", str(self.process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                self.process.terminate()
        else:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if platform.system() == "Windows" or _is_wsl():
                self.process.kill()
            else:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def launch_browser(url: str = SITE_URL) -> BrowserSession:
    """启动复用专用配置目录的独立浏览器窗口。"""
    ensure_data_dirs()
    profile_dir = browser_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    active_port = profile_dir / "DevToolsActivePort"
    # 避免上次异常退出时遗留的端口文件被误认为新浏览器。
    active_port.unlink(missing_ok=True)
    process = subprocess.Popen(
        [
            locate_browser(),
            "--remote-debugging-port=0",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile_dir}",
            "--new-window",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-notifications",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
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
    """监听同一浏览器中所有页面的请求。"""

    def __init__(self, debugger_port: int, *, capture_headers: bool = False) -> None:
        self.debugger_port = debugger_port
        self.capture_headers = capture_headers
        self.requests: list[dict[str, Any]] = []
        self._connections: dict[str, WebSocket] = {}
        self._request_records: dict[tuple[str, str], dict[str, Any]] = {}
        self._pending_headers: dict[tuple[str, str], dict[str, str]] = {}
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
            self._clear_page_state(endpoint)

    def _drain(self, endpoint: str, connection: WebSocket) -> None:
        while not self._stop.is_set():
            try:
                message = json.loads(connection.recv())
            except (TimeoutError, WebSocketTimeoutException):
                return
            except (OSError, WebSocketException, json.JSONDecodeError):
                self._connections.pop(endpoint, None)
                self._clear_page_state(endpoint)
                return
            method = message.get("method")
            params = message.get("params", {})
            request_id = params.get("requestId")
            key = (endpoint, str(request_id))
            if method == "Network.requestWillBeSent":
                request = params["request"]
                record: dict[str, Any] = {
                    "url": request["url"],
                    "method": request["method"],
                    "body": request.get("postData"),
                }
                if self.capture_headers:
                    record["headers"] = {
                        **_string_headers(request.get("headers", {})),
                        **self._pending_headers.pop(key, {}),
                    }
                    self._request_records[key] = record
                self.requests.append(record)
            elif method == "Network.requestWillBeSentExtraInfo" and self.capture_headers:
                headers = _string_headers(params.get("headers", {}))
                record = self._request_records.get(key)
                if record is None:
                    self._pending_headers[key] = headers
                else:
                    record.setdefault("headers", {}).update(headers)

    def _clear_page_state(self, endpoint: str) -> None:
        for key in [key for key in self._request_records if key[0] == endpoint]:
            self._request_records.pop(key, None)
        for key in [key for key in self._pending_headers if key[0] == endpoint]:
            self._pending_headers.pop(key, None)


def _string_headers(headers: object) -> dict[str, str]:
    if not isinstance(headers, dict):
        return {}
    return {str(name): str(value) for name, value in headers.items()}
