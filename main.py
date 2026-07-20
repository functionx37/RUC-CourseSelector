"""人民大学选课辅助 CLI。"""

from __future__ import annotations

import atexit
import asyncio
import logging

from src.browser import SITE_URL, launch_browser
from src.capture import collect_targets
from src.client import BrowserSessionCourseClient
from src.paths import COMMAND_HISTORY_PATH, RUN_LOG_PATH, ensure_data_dirs
from src.query_session import QuerySessionStore
from src.runner import CourseRunner
from src.targets import TargetStore

try:
    import readline
except ImportError:
    readline = None


HELP_TEXT = """可用命令：
  login         启动专用浏览器，手动登录教务系统并保存浏览器会话。
  choose        启动浏览器；采集目标课程、余量查询模板及当前会话。
  list          显示待选课程，每行包含课程、教师和教学班信息。
  delete <编号> 删除 list 中对应编号的课程。
  run           在配置的时间窗内运行待选课程任务；Ctrl+C 可停止。
  exit          退出程序。
"""


def configure_logging() -> logging.Logger:
    ensure_data_dirs()
    logger = logging.getLogger("ruccourse")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(RUN_LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def configure_command_history() -> None:
    """启用左右编辑、上下历史命令，并持久化历史记录。"""
    if readline is None:
        return
    ensure_data_dirs()
    try:
        readline.read_history_file(COMMAND_HISTORY_PATH)
    except OSError:
        # 目录可能由其他用户或受限环境创建；仍保留本次会话内的编辑和历史功能。
        pass
    readline.set_history_length(100)
    atexit.register(save_command_history)


def save_command_history() -> None:
    if readline is None:
        return
    try:
        readline.write_history_file(COMMAND_HISTORY_PATH)
    except OSError:
        pass


def login() -> None:
    print("将启动专用浏览器。请在其中手动登录教务系统，并勾选“记住我”或类似选项。")
    print("完成登录后回到此处按 Enter。")
    session = launch_browser(SITE_URL)
    try:
        input()
    finally:
        session.close()
    print("登录会话已保存在 .data/browser-profile/。会话过期后请重新登录。")


def collect(store: TargetStore, query_sessions: QuerySessionStore) -> None:
    result = collect_targets()
    if not result.targets:
        print("未捕获到选课提交请求。请确认已在目标课程上点击“选课”。")
        return
    confirmed = False
    for target in result.targets:
        print(f"捕获到：{target.class_name}（教学班 {target.teaching_class_id}，{target.semester_id}）")
        if input("保存到目标列表？[Y/n] ").strip().lower() not in ("n", "no"):
            confirmed = True
            if store.add(target):
                print("已保存。")
            else:
                print("该课程已在目标列表中。")
    if confirmed:
        if result.query_session.templates:
            query_sessions.save(result.query_session)
            print("余量查询会话已保存到 .data/query-session.json。")
        else:
            print("未捕获课程列表查询模板；run 无法查询余量。请重新 choose 并打开目标课程所属分类。")


def teacher_names(payload: dict) -> str:
    teachers = payload.get("skls_name", {})
    if isinstance(teachers, dict):
        names = teachers.get("name", [])
        if isinstance(names, list):
            return "、".join(map(str, names)) or "未知教师"
    if isinstance(teachers, str):
        return teachers or "未知教师"
    return "未知教师"


def list_targets(store: TargetStore) -> None:
    targets = store.list()
    if not targets:
        print("目标列表为空。")
        return
    for index, target in enumerate(targets, start=1):
        print(
            f"{index}. {target.class_name} | 课程：{target.course_name} | "
            f"教师：{teacher_names(target.payload)} | 教学班：{target.teaching_class_id}"
        )


def delete_target(store: TargetStore, argument: str) -> None:
    if not argument:
        print("用法：delete <编号>")
        return
    try:
        removed = store.delete(int(argument) - 1)
    except (ValueError, TypeError):
        print("请输入 list 中显示的有效课程编号。")
    else:
        print(f"已删除：{removed.class_name}")


def run(store: TargetStore, query_sessions: QuerySessionStore, logger: logging.Logger) -> None:
    targets = store.list()
    if not targets:
        print("目标列表为空，请先采集目标课程。")
        return
    try:
        query_session = query_sessions.load()
    except ValueError:
        print("余量查询会话文件无效。请重新执行 login 和 choose。")
        return
    if query_session is None:
        print("未找到余量查询会话。请先执行 choose，并在浏览器打开目标课程所属分类。")
        return
    print(f"将监控 {min(len(targets), 5)} 门课程；Ctrl+C 可随时停止。")
    print("将实时查询已选/最大人数；提交响应协议尚未确认，不会发送选课请求。")
    try:
        asyncio.run(CourseRunner(BrowserSessionCourseClient(query_session), store, logger=logger).run(targets))
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("抢课任务被用户中断。")
        print("\n抢课任务已停止，已返回主菜单。")
    except Exception:
        logger.exception("抢课任务异常结束。")
        print(f"抢课任务异常结束，已返回主菜单。详情见日志：{RUN_LOG_PATH}")
    else:
        print("抢课任务已结束，已返回主菜单。")


def main() -> None:
    logger = configure_logging()
    configure_command_history()
    store = TargetStore()
    query_sessions = QuerySessionStore()
    print("输入 help 以查看帮助。")
    while True:
        try:
            command, _, argument = input("CourseSelector> ").strip().partition(" ")
        except (KeyboardInterrupt, EOFError):
            print()
            return
        command = command.lower()
        if command in ("exit", "quit"):
            return
        try:
            if command == "login":
                login()
            elif command == "choose":
                collect(store, query_sessions)
            elif command == "list":
                list_targets(store)
            elif command == "delete":
                delete_target(store, argument.strip())
            elif command == "run":
                run(store, query_sessions, logger)
            elif command in ("help", ""):
                print(HELP_TEXT)
            else:
                print("未知命令。输入 help 查看命令。")
        except (FileNotFoundError, RuntimeError, TimeoutError) as error:
            logger.error("%s", error)
            print(f"操作失败：{error}")
        except Exception:
            logger.exception("操作出现未处理异常")
            print(f"操作失败，详情见日志：{RUN_LOG_PATH}")


if __name__ == "__main__":
    main()
