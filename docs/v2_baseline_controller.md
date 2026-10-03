# AITC V2 Phase 2：Baseline Controller

实施基线：`f59bb50`（Phase 1，经 PR #38 合入 main）。2026-10-03 重新 fetch，
本地分支和 `origin/main` 一致。主链与既有风险见 [基线审计](v2_baseline_audit.md)，
边界模型见 [Phase 1 契约](v2_contracts.md)。

## 封装范围

`app/core/control/policies/baseline.py::BaselineController` 组合现有单路口选择器
和全局协调函数。默认实现仍是 `call_dqn_select` 与 `coordinate`，不引入 LLM，
不新增规则、工厂或抽象基类。

`DQN_select` 当前是规则、经验表和时刻表的历史分发入口；它并非在线神经网络 DQN。
新控制器复用其中已接线的旧经验、新经验 pilot、时刻表、雷达与特殊车辆规则；
全局处理仍复用 Internet/Mixed/Flow、特殊路口、绿波、整数化和浮动值代码。
未给未上线的 RL/DQN 骨架创建虚假策略实现。

## 类型化入口与生产兼容入口

```python
from app.core.control.policies import BaselineController
from infra.data.traffic_adapters import snapshot_from_legacy

controller = BaselineController()
candidate = controller.predict(snapshot_from_legacy(legacy_request))
# candidate 是 SignalPlan；最终输出仍须全局协调及确定性校验。
```

`predict(TrafficSnapshot) -> SignalPlan` 严格校验 snapshot，深拷贝成旧请求后只调用
一次原选择器，不裁剪、不取整，也不把失败转换成全零成功。此入口为后续 DataHub/
Harness 提供可独立执行的单点候选接口；它不等于整个批次的最终方案。

生产入口保留以下两个方法：

| 方法 | 输入/输出 | 兼容约束 |
|---|---|---|
| `select_legacy(request)` | 原 `IntersectionControlRequest` → `(plan, coordinate, model, experience)` | 保留对象引用、列表/元组、原始诊断和异常 |
| `coordinate_legacy(action, previous, online, overflow)` | 原字典 → 原地修改后的方案字典 | 原四个位置参数、原地修改与跨轮状态 |

双入口共用同一选择器。诊断直接随原四元组返回，不保存 `last_diagnostics`，
避免 30 个线程共享控制器时串路口数据。控制器不会自行写结果仓库或下发。

保留兼容入口的原因是严格 `SignalPlan` 不能在旧全局规则之前接管行为：旧规则
可能修改浮点相位、重新选方案或保留失败后的列表，`phase_check` 还会夹限保留位。
本阶段不在生产热路径提前深拷贝、重新验证或把方案转换成新列表。

## 生产接线

`create_application()` 只构造一个 Baseline Controller，并注入周期管线：

```text
旧输入 → Receiver / cache / processor
       → IntersectionControlRequest
       → BaselineController.select_legacy
       → 原四元组与经验记录
       → BaselineController.coordinate_legacy
       → 旧 phase_check（确定性夹限）
       → 原 formatter / warehouse / TCP sender
```

`PeriodicDecisionPipeline` 仍兼容旧的 `dqn_select`/`coordinate` 构造参数；两者完整
传入时自动包装为控制器。新 `control_policy` 与旧回调同时提供时明确报配置错误，
缺少任一旧回调也报错。原实例回调属性仍可替换，默认绑定控制器的兼容方法。

`app/core/control/adapters.py` 的 formatter 导入改为函数内延迟导入，避免
`runtime.__init__ → application → policy → adapters → runtime` 的初始化循环。

## 保持的行为

- 全局顺序：Internet → Mixed → Flow → special → minimum cycle → green wave →
  int/floating → phase_check；重叠类别仍连续处理同一路口。
- 全局协调继续只传四个位置参数，没有顺手加入 extend 数据或重置绿波状态。
- 选择器异常仍由原管线记录；经验写入仍发生在结果赋值之前，写入失败保留默认结果，
  但已取得的 coordinate 仍进入下一轮上下文。
- `phase_check` 继续检查 `0..8`（包含 reserved），遇首个零停止；缺少配置只报告。
- 最终处理异常仍向应用循环传播，旧结果仓库不会被替换成半批或虚假的成功方案。
- 方案、modelInfo、经验日志、随机 score、零值截断和 TCP 换行报文格式保持原样。

类型化 `predict` 的非法候选会抛 Pydantic 校验异常；这是新入口的明确边界，
不能据此宣称旧生产链已有完整 Safety Gate。Phase 8 的安全回退尚未实施。
LLM 配置和 HTTP Agent 行为本阶段未改动；默认 `llm_required=false` 时旧生产控制
链继续独立运行。

## 回归验证

修改前，在隔离导出的 `f59bb50` 副本运行完整测试：152 项通过。
控制函数 9 项、全局处理器 23 项通过。经验模块仍有原先的 2 failures 与 1 error：
两个过期测试将 `1300086` 当作非 pilot 路口，一个测试仍导入已移除的 `Write_to_file`。
本阶段不通过改变白名单或恢复旧写入行为来消除这些失败。

新增单元/管线验证覆盖原始对象引用、严格候选接口、并发诊断、异常原样传播、
经验写入失败时的赋值顺序、仓库保留、策略注入、旧回调兼容和两种模块导入顺序。
还明确验证 `phase_check` 对第 8 槽的原地夹限没有被契约适配绕过。

黄金 fixture `test/fixtures/v2_baseline_controller.json` 在隔离的原始 `f59bb50`
副本生成，使用直接旧函数调用，之后才拿封装路径比较。其辅助脚本不重写任何配时公式。
固定工作日 2026-09-30 08:30/08:32（Asia/Shanghai）、随机种子 37、真实静态配置与
明确标记的测试传感器状态，并记录配置哈希。验证包含：

- 时刻表/规则、旧经验、新 pilot 成功、新经验文件缺失时的真实回退；
- 每轮 186 个真实选择器，完整旧全局协调与 phase_check，连续两轮保留互联网和绿波状态；
- coordinate 前后方案、夹限方案与报告、最终 payload 和 186 条 TCP 换行报文的全量哈希；
- Internet/Mixed/Flow、特殊路口复制、全零路口与四个绿波路口的可读检查点；
- 回放后恢复进程内共享状态和随机数状态，防止影响其他测试。

这组回归冻结单一工作日早高峰的行为。选择器按既有路口列表串行执行，以固定随机诊断；
生产仍使用原 30 线程，不宣称已经覆盖全部事件、日期分支或现场性能。
配置哈希变化需要审阅并重建 fixture，不得仅为让测试通过而刷新。

完整主测试包含本地 TCP/HTTP 和 MCP stdio 验证；限制本地通信的沙箱会影响这些
测试的执行，需要在允许本地监听/子进程通信的测试环境中运行。

2026-10-03 最终结果：编译及 diff 检查通过；主测试从 152 项增至 170 项全部通过，
控制函数 9 项、全局处理器 23 项通过；经验模块 111 项仍为相同的 2 failures、
1 error，没有新增失败。回放另在 UTC 与 Asia/Shanghai 环境验证通过。

```bash
.venv/bin/python -m compileall -q infra runtime agent app test
.venv/bin/python -m unittest discover -s test -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/control_functions/tests -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/control_functions/global_processors/tests -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/data_ANS/tests -p 'test_*.py'
```

## 下一阶段

Phase 3 在现有数据边界建立按路口隔离、窗口长度可配置的内存 DataHub。
本阶段不引入 LangGraph、模型网关、数据库或新的安全决策规则。
