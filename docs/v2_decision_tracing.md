# AITC V2 Phase 9：逐决策结构化日志

实施日期：2026-10-14。基线为 Phase 8 经 PR #45 合入 main 后的 `1841a67`。

## 记录边界

生产入口继续使用原 logger、控制台和每日轮转的 `server.log`。每次 `run_once()` 为每个
已配置路口生成独立 `trace_id`，同批次共用 `batch_id`；ID 使用 UUID，不消耗算法的
`random` 状态。记录格式为单行 JSON，`event=aitc.decision`、`schema_version=1`。

追踪对象属于当前调用，通过执行上下文传给路口 worker 和 LangGraph。共享组件不保存
last trace；每条记录在批次发布成功或失败后写出一次。

| 字段 | 含义 |
|---|---|
| trace_id / batch_id / intersection_id | 路口本轮身份、批次身份与路口 |
| input_timestamp | 原控制请求的 current_time；它是决策输入时间，不冒充原始传感器事件时间 |
| traffic_snapshot / snapshot_status | 原选择器前捕获的完整 TrafficSnapshot，包含真实全局预测和上一轮协调映射 |
| input_request | 无 DataHub 或本轮快照捕获失败时记录原请求，不用上一轮快照替代本轮 |
| control_policy | 当前装配的策略类型，生产为 BaselineController；不推测内部 selector 的具体分支 |
| route / expert_calls | 图节点路由、专家读取尝试与重试、状态、confidence、missing_fields；缓存复用明确标记 cached |
| tool_calls | 已通过权限检查并实际尝试的工具动作、参数、结果状态；失败尝试也保留 |
| llm_participated / model_calls / model_provider | 是否实际发起模型调用、尝试次数和 provider；超时也属于尝试 |
| model_reason / review | 认知层停止原因、严格且仅供参考的审查意见 |
| candidate_signal_plan / candidate_legacy | 单点原策略候选，先于经验写入与全局协调复制保存；非法候选只有原始诊断，无伪造契约对象 |
| final_signal_plan / final_legacy | Safety Gate 之后的方案；后续发布失败时仍只表示拟发布方案 |
| safety_report / fallback_reason / quality_issues / errors | 原安全报告、专家/模型/策略/安全降级原因、质量问题、分阶段错误 |
| status / publication_target | pending、published 或 batch_failed；published 仅表示成功替换 result_warehouse |
| latency_ms / stage_latency_ms | 使用 monotonic 性质的 perf_counter_ns 测量；总耗时截至批次结束，不含随后写日志的耗时 |

`stage_latency_ms` 包含聚合与 worker、控制图、经验写入、可选输入落盘、全局协调、安全、
检查报告写入、格式化和结果仓库发布。批次阶段耗时在同批记录中一致；聚合与 worker
阶段包含路口控制阶段，不能将所有字段直接相加当作总耗时。

快照记录完整保留普通 JSON 数据，不采用模型提示词的有界摘要。JSON 对象键转换为字符串；
非有限数值、不支持的对象、循环引用、异常映射键和极深结构使用带路径的 `trace_omitted`
标记，不调用不透明对象的 repr。所有记录使用 ASCII 转义并拒绝非标准 NaN JSON，避免
供应商字符串中的孤立 Unicode surrogate 破坏日志编码。

## 故障与业务语义

原算法、专家路由、调用预算、模型冷却、经验记录顺序、全局协调的四个参数、Safety Gate
和 TCP 报文结构保持原语义。追踪没有增加算法调用或重新查询历史状态。

模型与工具错误记录在本轮会话中；即使之后 Reviewer 成功，先前失败仍会出现在完整记录。
专家重试的每次尝试也会保留。模型审查、异常解释和专家错误日志带同一 trace_id，便于关联。

单路口原有异常处理继续产生旧缺省结果，记录原错误与 legacy fallback；经验写入失败时，
记录已计算的候选和之后实际进入最终链的缺省结果。批次协调、安全、格式化或仓库发布
抛异常时，记录 batch_failed 并原样传播异常，不能把拟发布方案标成 published。

意外的图异常使认知会话无法返回时，已经观察到的专家调用保留；启用了认知层的调用数和
参与标记为 null，明确证据不可得，不能伪装成 0 次调用。未启用认知层则可确定没有模型调用。
trace 的日志存储失败向 stderr 报告 trace_id 和错误类型，不把已成功发布的控制批次改成失败。

published 不证明 TCP 客户端已收到或信号机已执行。原异步广播和下游确认不在本阶段的决策
日志边界内。本阶段也不把发送时读取的经验激活清单当作算法实际消费版本；精确版本固定
需要原算法读取入口提供消费证据。不主动记录模型配置、鉴权头或完整模型回复。

## 查看记录

每条 JSON 是现有日志消息的一部分，前面仍有时间和日志级别：

```bash
rg '"event":"aitc.decision"' server.log
rg '"intersection_id":"1300068"' server.log
rg '"status":"batch_failed"' server.log
rg '具体的trace_id' server.log
```

不需要 Redis、数据库或外部可观测性平台，也没有为 trace 修改 TCP 字段。

## 验证

新增 30 项单元与集成测试覆盖严格字段、完整快照、输入不可变、候选/最终方案分离、
异常 JSON 值、Unicode、UUID 与随机数隔离、专家重试、有限工具查询及失败尝试、模型
超时与下一轮冷却、快照捕获失败、经验/worker/协调/格式化失败、日志写入故障和路口并发。

真实图与追踪参与的两轮 186 路口回放继续匹配未修改的黄金方案、旧检查报告、payload
和 TCP 字节，产生 372 个不同 trace_id。生产装配集成验证每个路口产生一条发布记录。

2026-10-14 验证：主套件 483 项、经验模块 118 项、控制函数 9 项、全局处理器 23 项
全部通过，compileall、pip check 和 git diff --check 通过。本阶段未连接真实模型 API。
