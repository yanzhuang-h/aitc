"""运行输出的本地文件仓库。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import threading
import time
from typing import Any


class FileRuntimeOutputStore:
    """保持旧日志目录格式的本地文件输出实现。"""

    def __init__(self, root: str | Path = "logs_data") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, category: str, data: dict[str, Any] | str, *, timestamp_line: bool = False) -> Path:
        text = self._serialize(data)
        path = self._path_for(category)
        with self._lock, path.open("a", encoding="utf-8") as file:
            if timestamp_line:
                file.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
            file.write(text + "\n")
            file.flush()
        return path

    def write_experience(self, exp_list: dict[str, Any], intersection_id: str) -> Path:
        directory = self.root / "EXP" / str(intersection_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"EXP_{datetime.now().strftime('%Y-%m-%d-%H-%M')}.json"
        with self._lock, path.open("w", encoding="utf-8") as file:
            json.dump({"EXP": exp_list}, file, ensure_ascii=False, indent=4)
        return path

    def _path_for(self, category: str) -> Path:
        directory = self.root / category
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{datetime.now().strftime('%Y-%m-%d')}_{category}.txt"

    @staticmethod
    def _serialize(data: dict[str, Any] | str) -> str:
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return data
        record = dict(data)
        record["AITC_SYS_TS"] = int(time.time())
        return json.dumps(record, ensure_ascii=False)
