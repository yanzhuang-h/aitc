# Day 4 学习笔记：Agent / Harness / 工具 / MCP

> 定位：Agent 层当前不在决策路径（摘掉 LLM 项目照跑），按"契约与边界"读，不做深入。
> 重做方向：Backlog A6（意图收敛 + 文件重命名 + 装饰器注册）、A7（目录结构）。

## 一、契约层

- `ToolResponse`：统一四段式 `status/summary/data/meta`；error 时 `data=None`；frozen 不可变。
- `ToolRegistry` / `IntentRegistry`：注册即路由，新增不改分发；`action` 字段供符号路由（不经 LLM）。
- `DataQueryTools`：7 工具（6 只读 + 1 生成）；`summary/full` 两档详情；limit 1-100 默认 20。
- `ControlFunctionTools`：3 控制工具；有 `data_processor` 时只给 `cross_id` 自动补实时上下文。

## 二、编排层

- `AgentHarness.handle(intent, payload)` 三层路由：显式意图 → 自主判断 → 兜底；`_record_call` 埋点 200 条。
- 现状 15 意图（绿波占 9）→ 收敛结论：真实意图仅「查询 / 单路口方案 /（可选）放行控制」。
- `SymbolicDataAgent`（纯规则）/ `QwenSignalTimingAgent`（两步 LLM，有回退）/ `QwenToolRouterAgent`（全工具路由，无回退）。
- `ControlProcessAgent`：规则给结果、模型给思考；LLM 失败回退固定文案，流程不中断。

## 三、LLM 客户端与 MCP

- `OpenAICompatibleLLMClient`：零依赖 urllib；超时 60s、重试 2 次指数退避；Qwen3 思考模式需显式关闭（防 `<think>` 截断 JSON）。
- `agent/mcp_server.py`：注册中心 → FastMCP 动态转换（Schema→inspect.Signature）；stdio 启动；新增工具自动暴露。

## 四、自答题答案

1. 新增工具现状改 4 处（schema/handlers/actions/方法）；重构后一个装饰器即可。
2. 防越权 = 层隔离：LLM 只有"生成"没有"下发"；写操作在 HTTP 层显式意图，不进 LLM 工具清单。
3. LLM 不可用：symbolic 可用 / agent.signal_timing 可用（回退）/ control_process 可用（文案回退）/ agent.tools 不可用（待补 fallback）。
4. summary/full：上下文经济 + 数据最小暴露（默认骨架，fields 给键名）。

## 五、现场演示（已验证）

- `build_unified_registry()` → 10 工具；`FastMCP list_tools` → 10 工具自动暴露；
- `get_timetable_plan("1300271")` → 真实时刻表方案 `[54,36,36,34,...]`（time_schedule_weekend）。

## 六、当天落地

- PR #30 `query_config_snapshot`→`query_config`（action `config.get`）+ A6；PR #31 A7；PR #32 A6 意图收敛结论。
