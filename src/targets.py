"""目标课程的本地存储与编辑。"""

from __future__ import annotations

import json
from pathlib import Path

from .models import CourseTarget
from .paths import TARGETS_PATH, ensure_data_dirs


class TargetStore:
    def __init__(self, path: Path = TARGETS_PATH) -> None:
        self.path = path

    def list(self) -> list[CourseTarget]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [CourseTarget.from_dict(item) for item in data]

    def add(self, target: CourseTarget) -> bool:
        targets = self.list()
        if any(item.key == target.key for item in targets):
            return False
        targets.append(target)
        self._save(targets)
        return True

    def delete(self, index: int) -> CourseTarget:
        targets = self.list()
        try:
            removed = targets.pop(index)
        except IndexError as error:
            raise ValueError("课程编号不存在。") from error
        self._save(targets)
        return removed

    def remove_key(self, key: str) -> bool:
        targets = self.list()
        remaining = [target for target in targets if target.key != key]
        if len(remaining) == len(targets):
            return False
        self._save(remaining)
        return True

    def _save(self, targets: list[CourseTarget]) -> None:
        ensure_data_dirs()
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps([target.to_dict() for target in targets], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
