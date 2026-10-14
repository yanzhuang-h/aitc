# 历史数据回放、模型白名单与现场采集交接

当前基线：Phase 10 / PR #47 的 `5d1f2bd`。本轮交付历史真实采集日志回放、周期模型白名单、
调用统计、安全配置清单和现场采集入口；尚未取得实时现场数据或新的权威安全规则。
用户已确认 `logs_data/flow`、`logs_data/radar` 为历史真实采集数据。

## 隔离回放

在项目根目录使用已安装 requirements.txt 的 Python 环境运行：

```bash
.venv/bin/python -m runtime.replay \
  --tcp logs_data/flow/2026-09-24_flow.txt \
  --http logs_data/radar/2026-09-24_radar.txt \
  --rounds 7 --interval 120
```

`--tcp`/`--http` 可重复，用于组合 flow/queue/stage/extend/雷达文件。每个文件默认读取最多
10000 条，报告明确记录截断；大文件可调 `--limit`。JSONL 对象、对象数组以及新采集器的
`{source, received_at, payload}` 均可读。坏行默认报错；显式 `--skip-invalid` 会记录坏行数量和位置。

两个独立进程分别运行原 Baseline 链和 V2 图链，随机种子默认 37，均保留原全局协调、
Safety Gate、格式化与仓库发布。每轮按原接收时间推进虚拟时钟，不改传感器字段或平移时间。
时间来源优先 received_at（带时区 ISO）→ AITC_SYS_TS → 原 ts/start_time/createTime/time；
最后一种标记 inferred。工作日/周末选择、小时配时和历史预测读取均使用回放日期。

默认禁用所有模型，输出和影子经验日志写入本次回放目录；生产端口、调度器与现场下发均未启动。
预测默认缺失，保留真实 None；只有 `--prediction-dir` 才读指定历史预测。比较结果退出码
0=一致，2=差异，1=回放失败。输入文件和业务 JSON 配置保持只读。

每次生成独立目录 `logs_data/replay/<时间>/`，包含：

- `comparison.json`：逐轮逐路口差异、窗口容量、输入时间来源、文件 SHA-256、配置文件启动时摘要。
- `baseline/`、`v2/` 的 `results.jsonl`、`decisions.jsonl`、`summary.json`：每轮结果、完整追踪和配置缺口。
- 发布时间仅代表结果仓库发布，不能证明现场收到或执行。文件摘要也不等于算法消费版本证据。

## 单路口 DeepSeek 与持续联调

保持本机 `.env` 中 `AITC_CONTROL_AGENT_ENABLED=false`，用 CLI 显式开启隔离进程中的模型：

```bash
.venv/bin/python -m runtime.replay \
  --tcp logs_data/flow/2026-09-24_flow.txt \
  --http logs_data/radar/2026-09-24_radar.txt \
  --model --roads 1300068 --rounds 3 --max-cloud-calls 9
```

生产新增 `AITC_CONTROL_AGENT_ROADS`（逗号分隔数字路口 ID）；默认空名单，空名单或名单之外
只走原控制和专家，不调用周期模型。未知路口启动失败，不能用 `*`。HTTP Agent 保持既有行为。
既有全路口测试替身显式填写测试名单，因此仍覆盖全部原路径。

每次模型尝试在决策追踪的新增 `model_attempts` 中记录阶段、状态、时延和供应商 token usage。
这些新增统计字段不保存请求头、凭证、完整响应或模型原文。状态区分 valid_action、invalid_action、error；
动作有效不意味着数据可用、审查正确或安全批准。报告给出有效动作比例、样本数、P50/P95
（最近秩法）、调用错误和本轮结束原因。P95 小样本只用于观察，不作为现场性能承诺。

预算检查采用 `轮数 × 名单路口数 × 单轮最大模型调用数` 的上界；超出 `--max-cloud-calls`
会拒绝云端回放。长时间联调示例：`--rounds 30 --interval 120 --pace-seconds 120 --max-cloud-calls 90`；
Baseline 加速运行，V2 模型轮次间按真实墙钟等待。仍是有限历史回放，不能替代实时压力测试。

报告保存 cache-hit/cache-miss 输入及输出 token。只有操作员同时填写
`--cache-hit-price`、`--cache-miss-price`、`--output-price`（每百万 token 单价，`--currency` 默认 CNY）
且所有调用返回完整 token 用量时，才计算 estimated_cost。缺价格、超时无 usage 或用量不完整
时成本为 null；这不是供应商账单。本轮没有擅自写入可能过期的价格。

## 本次历史验证及边界

- 7 轮、971 条（930 flow + 41 雷达/事件）全部进入回放，每轮 186 路口，V2 与 Baseline 输出一致；
  最后窗口 flow=0，验证真实 600 秒淘汰边界。每模式共 1302 条发布追踪。
- DeepSeek 3 轮只允许 1300068 调用，9 次动作均合法，P50 约 1.04 秒、P95 约 1.97 秒；
  结果与关闭模型一致。共 14507 token；未配置单价，实际账单需查看供应商控制台。
- 云端 3 轮截止时摄入 951 条，20 条较晚记录未进入该时间段，报告明确列出。
- 两个历史文件的传感器时间与接收时间均有明显差距，流量相差约 58 天；没有 queue 报文。
  本轮保留这些事实，不能将这些文件解释为同一时段的完整现场流量/排队/雷达观测。
- 该时间段每轮 137 valid、45 partial、4 no_action。partial 数量随实际方案变化，
  与旧冻结回放的 48 不同不代表补齐了安全规则。兼容输出、明确告警的既定策略保持不变。

## 安全规则核实与补齐

```bash
.venv/bin/python -m runtime.safety_audit
```

输出 `logs_data/replay/safety_inventory.json`：枚举 186 路口工作日/周末所有现有小时方案、
所需方案号和活动相位，列出缺路口、缺方案、缺相位边界及缺时刻表。此次 158 条
“路口×方案×缺规则”记录覆盖整个静态目录，不能与某轮 45/48 个 partial 路口直接比较。
原始时刻表的越界项单独标记为修正前检查，生产仍按 phase_check 修正后再次校验。

本工具不写配置，不把历史最小/最大时长当作真实安全限值。运维需提供当前生效方案、
逐相位上下界及规则依据；经核对后再修改 intersection_result_config.json，并重跑清单和回放。
行人最小绿、冲突矩阵、黄灯/全红约束待权威资料和明确协议后实现；当前不能宣称已覆盖。

## 交给现场运维的采集步骤

部署该分支和 requirements.txt 使用的 Python 3.11 环境，然后启动独立采集器：

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m runtime.capture --host 0.0.0.0 \
  --tcp-port 65433 --http-port 8089 --output logs_data/capture/site-first
```

采集器仅落盘，没有控制器、结果仓库或配时响应，不读取模型密钥。让运维将真实上报镜像
到该机器：TCP 65433 为 UTF-8 换行 JSON（对象或对象数组）；雷达/博研上报用
HTTP POST `http://采集机IP:8089/`。HTTP 的 received 仅确认采集条数。
此入口用于隔离运维网络上的镜像采集，无鉴权，不接公网；每个 JSON 帧上限 4 MiB。

优先采 1300068 或运维指定、已核对映射的单个路口，连续至少 30 分钟，包含流量、排队、
阶段/延长信息与对应雷达。记录机器时区与时间同步状态，不重写设备时间。Ctrl+C 停止。
输出 tcp.jsonl/http.jsonl 保留原 payload 和带时区 UTC 接收时间，可直接交给 replay。

请运维同时提供：

1. 路口 ID、检测器/雷达设备 ID 与方向/车道映射，覆盖的数据时段及设备缺失说明。
2. 当前生效方案和权威安全配置：相位含义、上下界、行人规则、冲突关系、黄灯/全红。
3. 若随后验证执行链，由信控平台导出带时间的命令接收及实际生效记录，包含路口、方案号、
   完整相位内容、成功/失败原因；当前 TCP 报文无 trace_id，需结合时间和方案内容关联。

只打包采集目录、映射和配置资料，不包含 `.env`。拿到新采集数据后先本机回放，再验证隔离
镜像环境持续运行；现场配时执行与规模扩大需运维确认链路和规则。Internet/EV 专家继续等待
真实来源与业务映射，不从缺失报文推导实现。

## 回归验证

本轮主套件 512 项、经验模块 118 项、控制函数 9 项、全局处理器 23 项，共 662 项通过；
compileall、pip check、git diff --check 通过。新增 15 项测试覆盖空/单路口名单、非法动作与
超时统计、来源/时间优先级、坏行与截断、成本缺失、窗口淘汰、两个真实子进程的 Baseline
对照、本地 DeepSeek HTTP 参数和白名单隔离，以及 TCP 分帧/HTTP 原报文采集。既有黄金
fixture、业务配时配置和下发 JSON 结构未改。
