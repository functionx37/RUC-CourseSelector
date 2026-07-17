"""领域模型与运行状态。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Availability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    SESSION_EXPIRED = "session_expired"


class SubmitResult(StrEnum):
    SUCCESS = "success"
    ALREADY_SELECTED = "already_selected"
    CATEGORY_LIMIT = "category_limit"
    NO_CAPACITY = "no_capacity"
    BUSY = "busy"
    SESSION_EXPIRED = "session_expired"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CourseTarget:
    """一条由用户在教务系统中手动生成的完整选课请求。"""

    teaching_class_id: str
    semester_id: str
    course_name: str
    class_name: str
    payload: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CourseTarget":
        teaching_class_id = str(payload.get("kkgl004id") or payload.get("id") or "")
        semester_id = str(payload.get("jczy013id") or "")
        course_name = str(payload.get("kcmc_name") or "未命名课程")
        class_name = str(payload.get("ktmc_name") or course_name)
        if not teaching_class_id or not semester_id:
            raise ValueError("未找到教学班 ID 或学期；请在实际选课页面重新采集。")
        return cls(teaching_class_id, semester_id, course_name, class_name, payload)

    @property
    def key(self) -> str:
        return f"{self.semester_id}:{self.teaching_class_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "teaching_class_id": self.teaching_class_id,
            "semester_id": self.semester_id,
            "course_name": self.course_name,
            "class_name": self.class_name,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CourseTarget":
        return cls(
            teaching_class_id=str(value["teaching_class_id"]),
            semester_id=str(value["semester_id"]),
            course_name=str(value["course_name"]),
            class_name=str(value["class_name"]),
            payload=dict(value["payload"]),
        )


@dataclass(frozen=True)
class RunConfig:
    max_courses: int = 5
    query_interval_seconds: float = 1.0
    max_submit_attempts: int = 1
    global_requests_per_second: int = 5
    busy_backoff_seconds: float = 5.0
