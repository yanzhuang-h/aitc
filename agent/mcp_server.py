"""AITC 工具注册中心 MCP 服务器（方向A：自身封装为 MCP 服务器）。

把 unified ToolRegistry（DataQueryTools 数据查询 + ControlFunctionTools 信号控制，
两者合并）动态封装为 MCP server：外部 MCP 客户端（VS Code / Claude Desktop /
Cursor 等）可通过 stdio 启动本模块，执行 ``list_tools`` / ``call_tool``
调用 AITC 的数据查询与放行控制工具。

新增工具只需在 registry 注册，MCP 层自动暴露，无需修改本文件。

启动方式（stdio，默认）::

    python agent/mcp_server.py

外部 MCP 客户端配置示例（mcp.json / claude_desktop_config.json）::

    {
      "mcpServers": {
        "aitc": {
          "command": "C:\\\\Users\\\\Finn\\\\.conda\\\\envs\\\\aitc\\\\python.exe",
          "args": ["agent/mcp_server.py"],
          "cwd": "<项目根目录>"
        }
      }
    }
"""

from __future__ import annotations

import copy
import inspect
import logging
import sys
from pathlib import Path
from typing import Annotated, Any

# 以独立进程启动时，保证能 import 项目根目录的顶层模块（Lambdas 等）。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import Lambdas

from agent.registry import ToolRegistry
from agent.tools import DataQueryTools
from app.config import RuntimeSettings
from app.core.tools import SingleIntersectionSignalTimingTool
from app.core.tools.control_function_tools import ControlFunctionTools
from infra.data import (
    ConfigService,
    DataKind,
    DataQualityMonitor,
    LongTermMemory,
    MemoryQueryLayer,
    ResultWarehouse,
    RuntimeDataProcessor,
    ShortTermMemory,
)

logger = logging.getLogger("aitc.mcp")

#: JSON Schema 类型到 Python 注解的映射，用于生成 MCP 工具参数签名。
_TYPE_MAP: dict[str, type] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def build_unified_registry(settings: RuntimeSettings | None = None) -> ToolRegistry:
    """构造统一工具注册中心（数据查询 + 信号控制），不启动任何网络服务器。

    装配与 ``runtime/application.py`` 保持一致，但只保留工具层依赖，
    供 MCP 服务器与其他进程复用。
    """
    settings = (settings or RuntimeSettings.from_environment()).validate()
    cache = ShortTermMemory({
        DataKind.FLOW: 600, DataKind.QUEUE: 240, DataKind.STAGE: 600,
        DataKind.EXTEND: 600, DataKind.ONLINE: 1800, DataKind.LATEST: 1800,
        DataKind.RADAR: 600, DataKind.BOYAN: 600,
    })
    config_service = ConfigService()
    warehouse = ResultWarehouse()
    repository = LongTermMemory(root=settings.runtime_data_dir)
    quality_monitor = DataQualityMonitor()
    query_service = MemoryQueryLayer(
        short_term_memory=cache,
        result_warehouse=warehouse,
        config_service=config_service,
        long_term_memory=repository,
        quality_monitor=quality_monitor,
    )
    overflow_warning_map = copy.deepcopy(Lambdas.map_lambda)
    radar_event_map = {key: {} for key in Lambdas.radar_event_list}
    signal_timing_tool = SingleIntersectionSignalTimingTool()
    data_tools = DataQueryTools(query_service, signal_timing_tool=signal_timing_tool)
    control_processor = RuntimeDataProcessor(cache, Lambdas)
    control_tools = ControlFunctionTools(
        data_processor=control_processor,
        overflow_warning_map=overflow_warning_map,
        radar_event_map=radar_event_map,
        flow_duration_seconds=settings.flow_duration_seconds,
    )
    control_tools.merge_into(data_tools.registry)
    return data_tools.registry


def _tool_callable(spec, registry: ToolRegistry):
    """把 ToolSpec 转成 FastMCP 可注册的调用函数（携带生成 schema 的签名）。"""

    async def _invoke(**kwargs: Any) -> dict[str, Any]:
        # FastMCP 会把带默认值的参数以 None 传入，这里与「未传」等价，统一过滤
        arguments = {key: value for key, value in kwargs.items() if value is not None}
        try:
            result = registry.invoke(spec.name, arguments)
        except Exception as exc:  # noqa: BLE001 - 外部调用，统一兜底
            logger.exception("MCP 工具调用失败: %s", spec.name)
            return {"status": "error", "message": f"{type(exc).__name__}: {exc}"}
        return result if isinstance(result, dict) else {"status": "ok", "data": result}

    _invoke.__name__ = spec.name
    _invoke.__doc__ = spec.description
    properties = spec.parameters.get("properties", {})
    required = set(spec.parameters.get("required", []))
    parameters = []
    for param_name, info in properties.items():
        annotation = _TYPE_MAP.get(info.get("type"), str)
        description = info.get("description") or ""
        if description:
            annotation = Annotated[annotation, description]
        default = inspect.Parameter.empty if param_name in required else None
        parameters.append(
            inspect.Parameter(
                param_name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation,
            )
        )
    _invoke.__signature__ = inspect.Signature(parameters)
    return _invoke


def create_mcp_server(registry: ToolRegistry | None = None):
    """创建 MCP 服务器，自动把 registry 全部工具注册为 MCP tools。"""
    from mcp.server.fastmcp import FastMCP

    registry = registry if registry is not None else build_unified_registry()
    mcp = FastMCP(
        "aitc",
        instructions="AITC 交通信号控制系统：运行数据查询与放行控制工具。",
    )
    for spec in registry.all_specs():
        mcp.add_tool(
            _tool_callable(spec, registry),
            name=spec.name,
            description=spec.description,
        )
    logger.info("MCP 服务器已注册 %d 个工具：%s", len(registry), registry.names())
    return mcp


def main() -> None:
    """以 stdio 方式启动 MCP 服务器。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    create_mcp_server().run()


if __name__ == "__main__":
    main()
