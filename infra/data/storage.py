"""Local file storage primitives for the data foundation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable


class JsonFileStore:
    """Small JSON/JSONL store used before introducing an external database."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def append_jsonl(self, name: str, item: dict[str, Any]) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
            file.write("\n")
        return path

    def read_jsonl(self, name: str) -> list[dict[str, Any]]:
        path = self.root / name
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                text = line.strip()
                if text:
                    records.append(json.loads(text))
        return records

    def write_jsonl(self, name: str, records: Iterable[dict[str, Any]]) -> Path:
        """原子替换 JSONL 文件，用于运行记录保留策略。"""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                delete=False,
            ) as file:
                temp_path = file.name
                for record in records:
                    file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                    file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
        return path

    def read_json(self, name: str, default: Any) -> Any:
        path = self.root / name
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def write_json(self, name: str, data: Any) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
        return path

    def list_files(self) -> Iterable[Path]:
        return self.root.rglob("*")
