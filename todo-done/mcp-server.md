# MCP 封装（方向A）：AITC 工具注册中心 → MCP 服务器

> 2026-08-25 · 依赖：`mcp>=1.0,<2`（安装于 aitc conda 环境，版本 1.29.1）

## 目标

把 AITC 统一工具注册中心（ToolRegistry）动态封装为 MCP 服务器，
外部 MCP 客户端（VS Code / Claude Desktop / Cursor 等）可通过 stdio
启动并执行 `list_tools` / `call_tool`，调用 AITC 的数据查询与放行控制工具。

后续「方向B：接入外部 MCP 服务器」可复用本设计：注册中心统一收口，
本模块只是其中一个 MCP 提供方。

## 实现

### `agent/mcp_server.py`

- `build_unified_registry(settings=None) -> ToolRegistry`
  构造统一注册中心（DataQueryTools 7 个查询工具 + ControlFunctionTools 3 个控制工具），
  与 `runtime/application.py` 装配保持一致，但**不启动任何网络服务器**，
  只保留工具层依赖（cache / config / warehouse / long-term / quality / processor）。
- `_tool_callable(spec, registry)`
  把 `ToolSpec` 转成 FastMCP 可注册函数：
  - 用 `__signature__` + `Annotated` 从 `spec.parameters`（JSON Schema）生成参数签名，
    FastMCP 自动转为 MCP inputSchema（参数名 / 类型 / required / default 均保留）。
  - 调用前过滤 `None` 值（FastMCP 会把带默认值的参数以 None 传入，
    与「未传」等价，需过滤避免工具校验报错）。
- `create_mcp_server(registry=None)`
  遍历 `registry.all_specs()` 动态注册全部工具；新增工具无需改本文件。
- `main()`：stdio 方式启动。

### 独立进程启动路径

`python agent/mcp_server.py` 运行时 `sys.path` 不含项目根目录，
文件顶部把项目根目录插入 `sys.path`，保证 `import Lambdas` 等顶层模块可用。

### MCP 客户端配置示例

```json
{
  "mcpServers": {
    "aitc": {
      "command": "C:\\Users\\Finn\\.conda\\envs\\aitc\\python.exe",
      "args": ["agent/mcp_server.py"],
      "cwd": "<项目根目录>"
    }
  }
}
```

## 测试（`test/test_mcp_server.py`）

1. `build_unified_registry` 含全部 10 个工具。
2. 直接 `invoke` 一个轻量工具（`query_latest_results`），返回 `status: ok`。
3. 每个工具带合法 JSON Schema 参数定义。
4. 真实 stdio 子进程联通：`list_tools` 10 个工具 + `call_tool` 成功。

## 验证

- 编译通过；全量测试 105 个通过（含新增 4 个）。
- 依赖变更：`mcp` 由 2.0.0 降级为 1.29.1（2.0.0 移除了 `FastMCP` 高层 API，
  1.x 是官方稳定高层接口，生态兼容性最好）。

## 后续（方向B 与多工具路由）

- 多工具路由：扩展 Qwen Agent，从全部 registry 工具中按自然语言选工具调用。
- 方向B：把外部 MCP 服务器接入注册中心，统一收口到 ToolRegistry。
