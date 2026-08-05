"""数据底座配置服务门面。

当前阶段继续复用旧配置接口的校验、兼容和文件锁逻辑，先把配置能力
从服务入口中隔离出来。后续可以在本模块内替换为 Redis、数据库或配置中心。
"""

from __future__ import annotations

from typing import Any

from lib.config_api import handle_config_request


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

