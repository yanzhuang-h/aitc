"""预测历史样本与每日预测结果的本地文件仓库。"""

from __future__ import annotations

import ast
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Iterable


class FilePredictionRepository:
    """兼容既有文件格式的预测数据仓库实现。"""

    def __init__(self, root: str | Path = "logs_data") -> None:
        self.root = Path(root)

    def read_history(self, category: str, windows: Iterable[tuple[datetime, datetime]]) -> list[dict[str, Any]]:
        """按时间窗口读取实时写出的历史预测样本。"""
        records = []
        for window_start, window_end in windows:
            for path in self._history_paths(category, window_start):
                if not path.exists():
                    continue
                records.extend(self._read_window_records(path, window_start, window_end))
                break
        return records

    def save_daily_predictions(self, category: str, prediction_date: datetime, predictions: dict[str, Any]) -> Path:
        """保存指定日期的完整预测结果。"""
        directory = self.root / f"{category}_predictions"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{category}_predictions_{prediction_date:%Y-%m-%d}.json"
        with path.open("w", encoding="utf-8") as file:
            json.dump(predictions, file, ensure_ascii=False, indent=2)
        return path

    def get_current_prediction(self, category: str, current_time: datetime) -> dict[str, Any] | None:
        """读取当前十分钟窗口对应的每日预测结果。"""
        path = self.root / f"{category}_predictions" / f"{category}_predictions_{current_time:%Y-%m-%d}.json"
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as file:
                predictions = json.load(file)
        except (OSError, json.JSONDecodeError):
            return None
        key = current_time.replace(minute=(current_time.minute // 10) * 10, second=0, microsecond=0).strftime("%Y-%m-%d-%H:%M")
        return predictions.get(key)

    def _history_paths(self, category: str, window_start: datetime) -> tuple[Path, Path]:
        filename = f"{window_start:%Y-%m-%d}_{category}.txt"
        return self.root / category / filename, self.root / filename

    @staticmethod
    def _read_window_records(path: Path, window_start: datetime, window_end: datetime) -> list[dict[str, Any]]:
        records = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                record = FilePredictionRepository._parse_line(line)
                if record is None:
                    continue
                try:
                    record_time = datetime.strptime(record["time"], "%Y-%m-%d-%H:%M")
                except (KeyError, TypeError, ValueError):
                    continue
                if window_start <= record_time < window_end:
                    records.append(record)
        return records

    @staticmethod
    def _parse_line(line: str) -> dict[str, Any] | None:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            try:
                value = ast.literal_eval(line)
            except (SyntaxError, ValueError):
                return None
        return value if isinstance(value, dict) else None
