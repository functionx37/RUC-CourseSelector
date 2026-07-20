"""项目内私有运行数据路径。"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / ".data"
BROWSER_PROFILE_DIR = DATA_DIR / "browser-profile"
LOG_DIR = DATA_DIR / "logs"
TARGETS_PATH = DATA_DIR / "targets.json"
RUN_LOG_PATH = LOG_DIR / "course-selector.log"
COMMAND_HISTORY_PATH = DATA_DIR / "command-history"


def ensure_data_dirs() -> None:
    for directory in (DATA_DIR, BROWSER_PROFILE_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(0o700)
        except OSError:
            # 某些 Windows 文件系统不支持 POSIX 权限。
            pass
