"""数据底座配置服务门面。

当前阶段继续复用旧配置接口的校验、兼容和文件锁逻辑，先把配置能力
从服务入口中隔离出来。后续可以在本模块内替换为 Redis、数据库或配置中心。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from lib.config_api import handle_config_request


class ConfigResource(StrEnum):
    """当前配置服务支持的资源类型。"""

    ROAD_INFO = "road_info"
    CROSS_INFO = "cross_info"


class ConfigService:
    """统一提供配置查询和写入能力。"""

    def handle_request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]] | None:
        """处理一次配置请求，返回状态码和响应体。

        路径不属于配置接口时返回 ``None``，由上层 HTTP 服务继续处理。
        """
        return handle_config_request(method, path, body)

    def query(self, resource: ConfigResource | str, cross_id: str) -> dict[str, Any]:
        """按资源和路口编号查询配置，供 HTTP 之外的调用方复用。"""
        resource_name = self._resource_name(resource)
        outcome = self.handle_request("GET", f"/{resource_name}/{cross_id}")
        if outcome is None:
            raise ValueError(f"unsupported config resource: {resource_name}")
        _, payload = outcome
        return payload

    def write(
        self,
        resource: ConfigResource | str,
        operation: str,
        payload: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        """写入配置，沿用旧接口的 add/update 校验和状态码。"""
        resource_name = self._resource_name(resource)
        outcome = self.handle_request(
            "POST",
            f"/{resource_name}/{operation}",
            payload,
        )
        if outcome is None:
            raise ValueError(f"unsupported config resource: {resource_name}")
        return outcome

    @staticmethod
    def _resource_name(resource: ConfigResource | str) -> str:
        resource_name = str(resource)
        if isinstance(resource, ConfigResource):
            resource_name = resource.value
        if resource_name not in {item.value for item in ConfigResource}:
            raise ValueError(f"unsupported config resource: {resource_name}")
        return resource_name
