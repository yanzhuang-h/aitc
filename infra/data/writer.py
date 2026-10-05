"""运行数据写入门面。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import ExperienceReleaseSettings
from .classifier import DataKind
from .output_store import FileRuntimeOutputStore


LOGGER = logging.getLogger(__name__)


class _ExperienceProvenance(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="ignore")

    release_id: str = Field(min_length=1)
    active_sha256: str = Field(min_length=1)


class RuntimeDataWriter:
    """通过本地输出仓库写入运行数据。"""

    def __init__(
        self, store: FileRuntimeOutputStore | None = None, *,
        experience_manifest_path: str | Path | None = None,
    ) -> None:
        self.store = store or FileRuntimeOutputStore()
        self.experience_manifest_path = (
            Path(experience_manifest_path) if experience_manifest_path is not None
            else ExperienceReleaseSettings().active_manifest_path
        )
        self._manifest_lock = threading.Lock()
        self._manifest_signature: tuple[int, int, int] | None = None
        self._manifest_provenance: dict[str, str] = {}

    def write(self, kind: DataKind, data: dict[str, Any]) -> None:
        self.store.write(self._resolve_category(kind), data)

    def write_flow_prediction(self, data: dict[str, Any] | str) -> None:
        self.store.write("flow_pre", data)

    def write_queue_prediction(self, data: dict[str, Any] | str) -> None:
        self.store.write("queue_pre", data)

    def write_send_result(self, data: dict[str, Any]) -> None:
        # 仅给本地日志副本补元数据，不能污染结果仓库或 TCP 报文。
        record = dict(data)
        provenance = self.get_active_experience_provenance()
        if provenance:
            record["AITC_EXPERIENCE_PROVENANCE"] = provenance
        self.store.write("send", record)

    def get_active_experience_provenance(self) -> dict[str, str]:
        with self._manifest_lock:
            try:
                stat = self.experience_manifest_path.stat()
            except FileNotFoundError:
                self._manifest_signature = None
                self._manifest_provenance = {}
                return {}
            except OSError as error:
                LOGGER.warning("无法读取经验发布清单 %s: %s", self.experience_manifest_path, error)
                self._manifest_signature = None
                self._manifest_provenance = {}
                return {}

            signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
            if signature != self._manifest_signature:
                try:
                    with self.experience_manifest_path.open(encoding="utf-8") as file:
                        provenance = _ExperienceProvenance.model_validate(json.load(file))
                    self._manifest_provenance = provenance.model_dump()
                except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
                    # 追溯元数据失效不能阻断已经完成的控制发送，也不能沿用旧版本。
                    LOGGER.warning("经验发布清单无效 %s: %s", self.experience_manifest_path, error)
                    self._manifest_provenance = {}
                    self._manifest_signature = None
                    return {}
                self._manifest_signature = signature
            return dict(self._manifest_provenance)

    def write_phase_check(self, data: dict[str, Any] | str) -> None:
        self.store.write("phase_check", data, timestamp_line=True)

    def write_experience(self, exp_list: dict[str, Any], intersection_id: str) -> None:
        self.store.write_experience(exp_list, intersection_id)

    def _resolve_category(self, kind: DataKind) -> str:
        mapping = {
            DataKind.FLOW: "flow", DataKind.QUEUE: "queue", DataKind.STAGE: "stage",
            DataKind.HEARTBEAT: "heartbeat", DataKind.ONLINE: "online", DataKind.LATEST: "online",
            DataKind.EXTEND: "extend", DataKind.OVERFLOW_WARNING: "overflowWarning",
            DataKind.RADAR: "radar", DataKind.RADAR_EVENT: "radar", DataKind.BOYAN: "boyan",
            DataKind.HISTORY: "history",
        }
        return mapping.get(kind, "history")
