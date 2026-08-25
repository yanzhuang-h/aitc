# Agent Harness 重构：意图注册表 + 三层路由

> 2026-08-25 · agent+harness 重构第 1 步

## 目标

把 AgentHarness 的意图分发从硬编码 if-else 升级为**注册表 + 三层路由**，
同时保持既有意图与 HTTP 协议完全兼容。

## 三层路由设计

1. **显式意图注册表**：`handle(intent, payload)` 按名称精确路由到已注册处理器。
2. **Agent 自主判断**：未注册的意图且 payload 带自然语言 `request_text` 时，
   交给自主判断 Agent（默认 `QwenToolRouterAgent`）从全部注册工具中自行选择。
3. **兜底逻辑**：既无显式意图又无法自主判断时，返回默认响应并附可用意图清单。

## 实现

### `agent/registry.py`

新增 `IntentSpec`（name / description / handler）与 `IntentRegistry`
（`register()` / `get()` / `names()` / `describe()` / `__contains__` / `__len__`），
风格与 `ToolRegistry` 一致。

### `agent/harness.py`

- `__init__` 新增 `intent_registry`（可选）与 `autonomous_agent`（可选，
  默认取 `qwen_tool_router_agent`）。
- `_register_intents()`：注册 6 个内置意图
  `signal_timing` / `agent.signal_timing` / `control_process` / `symbolic` /
  `agent.tools` / `autonomous`；新增意图只需在此登记。
- `handle()`：显式意图 -> `_handle_unregistered()`（自主判断 -> 兜底）。
- `_handle_autonomous()`：调用自主 Agent，返回标记 `routed_by: "autonomous"`。
- `_handle_unregistered()`：带自然语言时先自主判断（标记 `fallback_intent`），
  否则返回 `ToolResponse.error` + `available_intents` 清单。
- `intent_list()`：返回已注册意图清单，供调试与前端展示。

### `runtime/http_server.py`

新增 `POST /api/agent/query`（自主判断入口），GET 返回 405。

### `web/index.html`

接口测试页新增「Agent自主判断」选项（`/api/agent/query`）。

## 测试

- `test/test_symbolic_agent.py`：IntentRegistry 基础、注册表精确路由（兼容旧行为）、
  未知意图+自然语言->自主判断、未知意图无自然语言->兜底、显式 autonomous 意图。
- `test/test_http_runtime_server.py`：`/api/agent/query` POST 200 / GET 405。

## 验证

全量测试 119 个通过（此前 112 + 新增 7）。

## 后续（待做）

- 绿波服务纳入 harness ✅：`green_wave.*` 意图组（status/config/plan/list/get/
  validate/update/delete/enabled），HTTP 层绿波路由全部改走 harness，
  doc1/doc2 双格式与对外接口完全兼容。
- Harness 可观测性 ✅：每次 `handle()` 记录意图、路由方式（registry/autonomous/
  fallback）、耗时、状态与错误；`recent_calls(limit)` 查询；HTTP
  `GET /api/agent/calls`；前端「Agent调用记录」选项。
- 生命周期收敛：Agent/工具装配纳入 `AITCApplication` 统一管理。
- 决策结果契约统一（可选）。
