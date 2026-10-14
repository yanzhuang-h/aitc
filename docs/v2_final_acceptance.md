# AITC V2 Phase 10：最终验收与运行交接

实施日期：2026-10-14。基线为 Phase 9 经 PR #46 合入 main 后的 `7612ee9`。
本阶段完成仓库内算法和协议闭环验收；真实模型质量与现场运行尚未验收。

## 实际验收链路

```text
真实 TCP 字节流 / 本地 HTTP 雷达上报
→ 原接收、落盘与 Traffic DataHub
→ 原聚合与预测、完整请求、本轮快照
→ Video / Radar Expert、LangGraph、可选 Planner / Reviewer
→ 原 Baseline selector、全局协调
→ Safety Gate、fallback、决策追踪
→ 原结果仓库、同一 TCP 连接上的换行分帧广播
```

`test/integration/test_v2_acceptance.py` 使用生产 `create_application()`、原选择器、专家、
工作日时刻表、静态配置、格式化和输出仓库。输入和模型服务只监听本机随机端口。
测试关闭生产调度与后台广播周期，显式执行单轮决策及广播；TCP 接收端并发读取，覆盖
有限 socket 缓冲区下的真实分帧收发。

本地模型 HTTP 测试服务返回固定严格动作，并支持 HTTP 503、实际 socket timeout 和非法
直接设灯动作。它验证传输与 Harness，不代表模型理解交通状态的能力，不访问远端 API。

## 最初九项要求的验证映射

下列方法均位于 `test/integration/test_v2_acceptance.py`，既有分阶段套件也继续执行。

| 要求 | 完整闭环验证 |
|---|---|
| 无 LLM 正常配时 | `test_no_llm_video_only_reaches_original_tcp_output`：禁止模型网络调用，仍广播 186 个路口 |
| Video-only | 同上：真实视频解析后只走 Video，完整流量、排队和缺失预测进入快照 |
| Video 缺关键数据 → Radar fallback | `test_missing_video_queue_and_http_radar_take_real_fallback_path`：缺 queue_map 的视频走 Radar，真实 HTTP 雷达数据进入状态 |
| LLM 不可用 | `test_real_http_503_preserves_control_and_cools_subsequent_intersections`：输出与 Disabled 一致，后续路口跳过故障模型 |
| Model timeout | `test_real_socket_timeout_preserves_control_and_is_traced`：实际 HTTP 延迟触发 socket timeout，原控制和广播继续 |
| Candidate plan 安全校验 | `test_model_accept_does_not_bypass_final_safety_or_tcp_fallback`：模型 ACCEPT 不能批准协调后损坏的方案，原时刻表 fallback 重验后广播 |
| legacy input/output compatibility | 真实 TCP/HTTP 输入、仓库与广播 JSON 相等、无 trace 协议字段；既有六个协议 fixture 和完整黄金回放继续执行 |
| DataHub history | `test_real_ingestion_history_is_bounded_and_cannot_cross_intersections`：真实输入连续三轮，窗口为二，按路口隔离 |
| baseline regression | `test_combined_graph_safety_tracing_and_tcp_match_frozen_two_round_baseline`：Disabled 与 Mock 两模式的图、安全门、追踪、格式化及发送共同匹配原两轮 186 路口黄金结果 |

另有真实 Qwen/DeepSeek HTTP 参数验证、非法模型设灯拒绝和冷启动修复前后业务输出比较。
既有 JSON 黄金 fixture 与配置摘要均未修改，没有用新生成的期望值替代基线。

保留已有 `test/unit/`、`test/integration/`、`test/fixtures/`，不另建重复的 `tests/` 根目录。
Phase 4 报文 fixture 移至共享 `test/fixtures/v2_acceptance.py`，避免重复定义。

## 冷启动契约修复

真实预测仓库缺当前文件时返回 `None`。旧 TrafficSnapshot 只接受字典，会将这两个合法
缺失值当成契约错误，保留原控制但无法记录快照和历史。

本阶段在十五字段的唯一来源 IntersectionControlRequest 中，将 predicted_flow 和
predicted_queue 定义为 `dict | None`。默认值仍为原空字典；缺文件的 None 在 adapter、
DataHub、历史、模型摘要和追踪中保留，不改写传给原算法的请求。列表、字符串、布尔和数字
仍不能冒充预测映射。模型摘要的 missing_prediction_fields 明确说明预测不可用。

严格往返与 TCP 冷启动回归证明：快照现在能记录，原配时和广播 payload 保持一致。
以前明确期待冷启动丢失快照的集成断言已改为验证 None 被原样保存，186 路口输出比较仍保留。

## 重复运行与 CI

从仓库根目录、使用已安装 requirements.txt 的 Python 环境运行：

```bash
.venv/bin/python -m compileall -q infra runtime agent app test
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s test -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/data_ANS/tests -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/control_functions/tests -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/control_functions/global_processors/tests -p 'test_*.py'
```

只运行最终闭环验收：

```bash
.venv/bin/python -m unittest test.integration.test_v2_acceptance
```

CI 执行 pip check 和全部四个套件，补齐此前仅本地执行的控制函数与全局处理器回归。
本阶段新增 11 项闭环测试、2 项冷启动契约测试和 1 项非法预测输入兼容回归。

2026-10-14 最终验证：主套件 497 项、经验模块 118 项、控制函数 9 项、全局处理器 23 项，
合计 647 项通过；compileall、pip check、git diff --check 通过。修改前主套件为 483 项。

## 启动与观察

```bash
AITC_LLM_ENABLED=false .venv/bin/python Server_AITC.py
```

模型增强按 [README](../README.md) 和 [模型网关](v2_model_gateway.md) 配置。
LLM_ENABLED 允许模型调用，CONTROL_AGENT_ENABLED 单独控制周期增强，默认关闭；使用实际
环境名 `AITC_LLM_ENABLED`、`AITC_CONTROL_AGENT_ENABLED`。显式 `AITC_LLM_REQUIRED=true` 会
要求启动时模型就绪。调用次数和 socket timeout 有预算，但不是整个决策的严格总 deadline。

```bash
rg '"event":"aitc.decision"' server.log
rg '"status":"batch_failed"' server.log
rg '具体trace_id' server.log
```

检查模型参与、候选/最终差异、safety_report 和 fallback_reason。published 仅表示仓库
替换成功，不能证明客户端收到或信号机执行。TCP 协议和原异步广播机制保持不变。

## 后续业务补齐项

- 冻结回放每轮 134 个 valid、48 个 partial、4 个既有 no_action。依此前确认的兼容策略，
  partial 保持输出且 safe=null；需真实静态规则后再全面拦截。
- 行人、冲突矩阵、黄灯/全红等约束没有可信配置，本阶段未编造限值。
- Internet Expert 尚缺统一全局路段状态定义；原互联网算法继续在全局协调执行。
  EV/V2X 没有已接线的输入与映射，两者保留明确 TODO。
- 生产 Baseline 主要使用经验、时刻表和规则，本阶段未新增独立在线神经网络 DQN/RL。
- 真实 Qwen/DeepSeek 的结构化成功率、时延、成本及现场交通效果尚未验证。
- 经验激活清单不能证明单次算法实际消费版本，精确固定仍需读取入口的消费证据。

Phase 0–10 的仓库内阶段工作完成后，可针对真实模型接入和业务配置补齐开展验收；测试
数量不能替代现场确认。
