# AITC V2 Phase 1：交通与控制契约

基线：`3e8c7b9`，Phase 0 复核见 [基线审计](v2_baseline_audit.md#141-phase-0-复核2026-10-02)。
本阶段新增契约及兼容 adapter，生产装配、配时算法、全局协调、夹限及发送代码保持原样。
唯一涉及旧请求的修改是修正 `queue_vector` 类型注解，构造与默认值不变。

## 真实主链与阶段边界

```text
Server_AITC.py -> create_application
  -> TCP/HTTP -> Receiver -> ShortTermMemory
  -> PeriodicDecisionPipeline -> RuntimeDataProcessor/cache_processor
  -> call_dqn_select -> DQN_select（规则 / 经验 / 时刻表）
  -> coordinate -> phase_check -> format_result
  -> ResultWarehouse -> TCP broadcast -> ResultSender
```

当前 HTTP Agent 与周期链并列。没有 LLM 服务时，默认 `llm_required=false` 的
生产链可以独立运行；本阶段没有新增 `LLM_ENABLED` 或更改启动检查。
Phase 2 才封装 Baseline Controller，后续阶段再实现 DataHub、Expert、LangGraph、
Model Gateway 和独立 Safety Gate。这里的 schema 校验不代表完整交通安全校验。

目录沿用现有业务边界，参考
[fastapi-best-practices 的业务领域组织方式](https://github.com/zhanymkanov/fastapi-best-practices#project-structure)，
没有机械迁移仓库或建立新的抽象控制层。

## 四个契约

| 契约 | 定义 | 含义 |
|---|---|---|
| `SignalPlan` | `app/core/control/schemas.py` | 路口 ID、八个相位槽、保留位、方案号 |
| `RawTrafficEvent` | `infra/data/traffic_schemas.py` | 已分类原始报文、TCP/HTTP 来源、接收时间、可选路口 ID、质量问题 |
| `TrafficSnapshot` | 同上 | 每路口一轮十五字段算法上下文；继承现有 `IntersectionControlRequest` |
| `ExpertTrafficState` | 同上 | video/radar/internet/ev 来源、snapshot observation、missing_fields、confidence |

契约使用 Pydantic 2，禁止额外信封字段、字符串到数值的隐式转换、布尔数值和
NaN/Infinity。`TrafficSnapshot` 是 Pydantic dataclass；其 schema 和 JSON 校验可使用
`TypeAdapter(TrafficSnapshot)`。两个 ID/时间字段增强边界校验，其余字段定义复用旧请求。
`ExpertTrafficState` 的 observation 复用该 snapshot，不重建一套交通状态字段。

原始 payload、传感器明细和旧算法 maps 中仍保留异构 `Any` 值：当前数据来源缺少
统一的明细协议，不能凭空把供应商字段规范化。严格校验信封和顶层容器，旧报文必需字段
问题仍通过原有 `validate_contract()` 描述，不把历史非阻断校验升级为生产拒收。

## SignalPlan 兼容规则

```python
from app.core.control.adapters import signal_plan_from_legacy, signal_plan_to_legacy

legacy = [42, 18, 44, 0, 0, 0, 0, 0, 0, 0]
plan = signal_plan_from_legacy("1300068", legacy)
assert signal_plan_to_legacy(plan) == legacy
```

- `phase_times` 固定八个槽，对应旧 `plan[0:8]`；保留零值和零值后的内容。
- `reserved` 对应 `plan[8]`，不强制改成零。
- `program_id` 对应 `plan[9]`；保留 int/float/string 类型，字符串兼容现有 formatter 测试。
- 相位时长须是非负有限数值，但不提前 `int()`，不分配新时长，不裁剪业务上下界。
- 不推断相位对应的通行方向，不计算周期，不宣称一个 plan 已通过交通安全检查。
- `signal_plan_to_payload()` 复用现有 `format_result()`；零值截断、道路映射、随机
  modelInfo 和十元素全非零的历史行为保持一致。未定义第二套 TCP 字段模型。
- schema 不代替 `DecisionResult`：后者仍负责旧结果仓库与报文字典兼容。

## 输入与状态 adapter

`infra/data/traffic_adapters.py` 提供：

```python
raw_event_from_legacy(payload, source=DataSource.TCP, received_at=received_seconds,
                      intersection_id=resolved_intersection_id)
raw_event_to_legacy(event)
snapshot_from_legacy(request)
snapshot_to_legacy(snapshot)
```

原始事件 adapter 复用分类优先级及 `CONTRACTS`，不重复定义每种报文的必需字段。
`received_at` 必须由接入方传入 Unix 秒，报文中的 `ts/time/start_time/createTime`
原样保留，避免混淆接收时间与报文时间。路口 ID 由已有映射在调用边界解析后传入，
设备号、检测器号、rid 不会被冒充为路口 ID；未知或无法解析的数据可保留 `None`。

snapshot adapter 深拷贝状态，保留 LRUD 顺序、list/dict 排队形态、秒级 key 和
跨轮 coordinate 数据，不污染旧请求。向旧算法返回的仍是原 `IntersectionControlRequest`。
Python adapter 往返保留 map 的整数/浮点 key；JSON 对象 key 会变成字符串，
因此 snapshot JSON 用于 schema/日志交换，不能直接当作跨进程无损算法回放格式。

## 验证与已知范围

CI 的现有 `unittest discover -s test` 会递归发现 `test/unit/` 和 `test/integration/`。
保留现有 `test/fixtures/`，不为目录形式新建第二套测试根目录。

新增验证包括：

- 四个契约的严格 schema、无隐式数值转换、额外字段拒绝、来源与置信度约束；
- 原始分类优先级、质量问题非阻断、深拷贝隔离、十五字段 snapshot 往返；
- 6 个冻结的 formatter 样例：3 个真实时刻表、全零、零值间隙与浮点/字符串方案、
  十个槽全部非零；逐一检查旧 TCP payload、仓库和换行发送字节；
- 固定时刻表和随机种子，实际运行 `1300103` 选择器，再经过 `phase_check` 和
  formatter，对比 adapter 前后的方案、诊断、夹限报告与最终报文；
- 缺省 modelInfo 的随机输出保持一致。

`test/fixtures/v2_signal_plan_baseline.json` 的报文由基线 formatter 生成；真实时刻表
记录来源路径，另外三个明确为协议边界样例。这不是所有 186 个路口、绿波和特殊规则
的黄金回放集；完整 Baseline Controller 回归将在 Phase 2 扩充。

阶段验证命令：

```bash
.venv/bin/python -m compileall -q infra runtime agent app test
.venv/bin/python -m unittest discover -s test -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/control_functions/tests -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/control_functions/global_processors/tests -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/data_ANS/tests -p 'test_*.py'
```

经验模块在修改前已有 2 failures 和 1 error，详见基线审计。Phase 1 不修改这些
测试所涉及的 pilot 白名单或历史文件导入问题。

2026-10-02 阶段验证结果：编译通过；主测试由 137 项增至 152 项全部通过；
控制函数 9 项、全局处理器 23 项全部通过。经验模块仍为 111 项中的相同
2 failures 和 1 error，没有新增失败。

后续架构目标：

> AITC uses an LLM-driven agent as the cognitive layer and a constrained harness as the execution layer.
> Existing deterministic and reinforcement-learning traffic control policies remain independently executable,
> while the LLM provides planning, tool routing, anomaly reasoning, and policy review under deterministic safety constraints.

这是后续阶段的目标，不表示当前已有在线 RL、LangGraph 或 Qwen Reviewer 装配。

Phase 2 的生产接线与兼容边界见 [Baseline Controller](v2_baseline_controller.md)。

Phase 3 的状态中心、来源查询和最近 N 轮历史见 [Traffic DataHub](v2_datahub.md)。

Phase 4 的 Video/Radar 提取、统一状态及 Internet/EV 接口见 [交通专家](v2_traffic_experts.md)。
