"""余量查询所需的浏览器会话与请求模板。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import CourseTarget
from .paths import QUERY_SESSION_PATH, ensure_data_dirs


@dataclass(frozen=True)
class QueryTemplate:
    """一条由浏览器实际发出的课程列表查询请求。"""

    url: str
    body: str
    headers: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "body": self.body, "headers": self.headers}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "QueryTemplate":
        url = value.get("url")
        body = value.get("body")
        headers = value.get("headers")
        if not isinstance(url, str) or not isinstance(body, str) or not isinstance(headers, dict):
            raise ValueError("查询模板格式不完整。")
        return cls(url, body, {str(name): str(header) for name, header in headers.items()})


@dataclass(frozen=True)
class QuerySession:
    """按课程分类索引的余量查询模板。"""

    templates: dict[str, QueryTemplate]

    def template_for(self, target: CourseTarget) -> QueryTemplate | None:
        category = target.payload.get("kclbMapper") or target.payload.get("kclbcode")
        return self.templates.get(str(category)) if category is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "templates": {
                category: template.to_dict() for category, template in self.templates.items()
            },
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "QuerySession":
        templates = value.get("templates")
        if not isinstance(templates, dict):
            raise ValueError("查询会话不含模板。")
        return cls(
            {
                str(category): QueryTemplate.from_dict(template)
                for category, template in templates.items()
                if isinstance(template, dict)
            }
        )


class QuerySessionStore:
    """保存会话凭据和模板到仅当前用户可读的私有文件。"""

    def __init__(self, path: Path = QUERY_SESSION_PATH) -> None:
        self.path = path

    def load(self) -> QuerySession | None:
        if not self.path.exists():
            return None
        return QuerySession.from_dict(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, session: QuerySession) -> None:
        ensure_data_dirs()
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
