# 调整候选清单（Backlog）

> 汇总学习 Day 1（入口/装配/协议）与 Day 2（数据底座 `infra/data`）过程中发现的、待后续统一处理的调整点，避免遗漏。
> 已落地的事项不入此表（见各 PR）；每项注明来源、现状、建议与优先级（低/中/高）。
> 处理原则：先小后大、行为不变优先；涉及算法行为的事项需单独说明影响面。

## A. 架构与模块化

| # | 事项 | 现状 | 建议 | 优先级 |
| --- | --- | --- | --- | --- |
| A1 | HTTP 服务拆分 | `runtime/http_server.py`（539 行，约 30 个路由）一锅端：雷达/博研数据收取 + 前端页面 + 配置 + Agent + 绿波 + 健康检查 | 数据收取（雷达/博研）与 TCP 同级；其余管理面服务单开文件（方向：FastAPI，Day 1 已定） | 高（后期集中做） |
| A2 | 存储升级路线 | 短窗=内存 deque；长仓=JSONL；结果仓=内存列表 | 短窗→Redis；长仓→SQLite（首选）；结果仓→Redis；只动三个实现文件，调用方零改动 | 中（视部署规模） |
| A3 | 两套写入收敛 | `logs_data/*.txt`（人读兼容 + 补 `AITC_SYS_TS`）与 `runtime/*.jsonl`（程序查）并存 | `runtime/*.jsonl` 做唯一真相源，`logs_data` 降级为兼容视图；先盘点消费者（flow_pre/queue_pre 预测、EXP、现场人工）再迁移；不换 YAML | 中 |
| A4 | 配置资源同步来源抽象 | 4 类走 Nacos（floating_value/intersection_result/road_state/time_schedule），2 类走 HTTP 文件（road_info/cross_info）；`ConfigService` 门面已收口 | 暂不抽"同步源接口"（YAGNI）；出现第二类配置中心再抽象 | 低 |
| A5 | 接入层吞吐优化 | TCP 65432 + HTTP 8088 分端口：信控平台走 TCP（长连接、量最大），雷达/博研走 HTTP；旧原因="一个端口忙不过来" | 协议拆分保留（设备协议决定）；方向：异步接收/独立写线程池，或统一网关+消息队列（MQ）；按规模再定 | 中 |
| A6 | Agent 层重构（需求驱动） | 现状：五类组件叠加（SymbolicDataAgent / QwenSignalTimingAgent / QwenToolRouterAgent / ControlProcessAgent / AgentHarness）+ 双路由（IntentRegistry + action 符号路由）+ 15 个意图（绿波占 9 个，实为资源 CRUD）；工具需四处声明；文件命名不清晰（qwen_agent.py 一文件三类、tools.py 泛指） | 意图收敛（2026-09-30 结论）：真实意图仅「查询 / 单路口方案 /（可选）放行控制」2-3 个；symbolic+agent.tools+autonomous 三合一、signal_timing+agent.signal_timing 二合一、绿波 9 意图移出 harness 做独立资源路由；文件按组件拆分重命名；装饰器式工具注册；保留 `/api/agent/*` 兼容 | 中（远期） |
| A7 | 目录与模块结构重构 | 现状：根目录混放运行入口与离线脚本；`app/core/tools` 反向依赖 `agent.registry`；`lib` 内分域不完全；`agent` 与运行时装配耦合 | 参照成熟分层惯例（FastAPI 风格 `app/{api,core,models,services}` 或 domain/application/infrastructure）+ `架构.png` 模块边界（数据底座/控制模块/安全引擎）分步调整；先收敛根目录（C4/C5）、注册中心下沉、lib 分域、agent 服务化；不照搬图，逐项迭代 | 中（远期） |
| A8 | MCP 多服务器化 | 现状：单个 `agent/mcp_server.py` 暴露全部 10 个工具 | 按功能域拆多个 MCP server（数据查询 / 信号控制 / 绿波管理等），各自独立进程与配置；复用统一注册中心按域过滤 | 低（远期） |

## B. 数据底座待办

| # | 事项 | 现状 | 建议 | 优先级 |
| --- | --- | --- | --- | --- |
| B1 | 内部时间归一化 `event_ts` | `ts/time/start_time/createTime` 名字各异（上游协议决定），转换散落在 `cache_processor.process_*`（flow/queue/stage 毫秒//1000，radar/boyan `int(ts)`，extend/online/latest 用到达时间） | receiver 落库前补统一 `event_ts`，不动 payload | 中 |
| B2 | 无调用方清理 | `heartbeat` 无任何消费者（仅 debug 日志+入库）；`receive_many`/`ingest_*_item` 全仓无调用方；`DataContract.intersection_fields` 无读者；`DataKind.UNSUPPORTED` 无生产者 | 逐个确认后删除或注释标注；heartbeat 可考虑做成"设备在线状态表" | 低 |
| B3 | radar 长期记录路口为空 | 解析器不认 `deviceNo`，`intersection_id` 恒 null；窗口却靠 `device_to_location` 把关，两路径不对称 | 确认语义后补解析或文档说明 | 低 |
| B4 | radar_event 三类事件无消费者 | 四类事件仅 `OverFlow` 进决策，`QueueOverrun/Parking/Speeding` 只收不用 | 确认占位还是补处理（属算法行为，单独评估） | 中 |
| B5 | `latest` 无决策消费者 | 快照里有、决策不读 | 确认语义或清理 | 低 |
| B6 | `schemas.py` 注释中文化 | 顶部与部分 docstring 为英文，与全仓中文约定不一致 | 统一中文 | 低 |
| B7 | `read_jsonl` 无逐行容错 | 坏行直接抛（现状靠写端保证） | 可选加固 | 低 |
| B8 | 广播断连半包 | `ResultSender` 逐条 `sendall`，断连客户端可能收到半包 | 接收端按 `\n` 分帧已兜底，保持旧行为，仅记录 | 低 |
| B9 | CONTRACTS 条目 kind 重复 | 字典键与构造首参各写一遍 | 可选收敛（小冗余） | 低 |
| B10 | 字段字典待核实项 | `ycsb_cpzxd`、`rid`、`distance`、`carNums`、`car_nums[].queue/all` 为推断；`ycsb_xsfx` 编码与 `ycsb` 前缀待确认 | 后续对照飞书文档/数据核实，扩展为详尽版字典 | 低 |
| B11 | Lambdas 资产整理 | `Lambdas.py`（3392 行）集中映射字典、结构模板与内联配置大表；命名不统一（`aibi_to_xinkongji`、`huawei_device_to_location` 等拼音）；部分资产与 `lib/*.json` 重复 | 拆分 json 资产、规范化英文命名、去重；只动组织方式，不动算法语义 | 低 |
| B12 | 存量拼音命名改造 | `lib/` 层拼音文件与标识符：`cha.py`、`cha1.py`、`ti.py`、`lvbotest.py`、`tong_yong_biao.py`、`buqi_new2.0.py`、`data_chou.py`、`E_T_new.py`、`Get_time_map`、`Get_Fine_map`、`Init_add` 等 | 新代码一律英文命名（见项目指令）；存量按模块分批改名（文件改名需同步 import 与 json 路径引用），不改行为 | 低 |

## C. 配置抽象（路线微调候选，未落地项）

| # | 事项 | 现状 | 建议 | 优先级 |
| --- | --- | --- | --- | --- |
| C1（#4） | 配置文件路径硬编码 | `app/core/control/synergy/green_wave_api_adapter.py`、`phase_check.py`、`time_schedule/get_sch_for_cross.py` 写死路径 | ✅ 已落地：`app/paths.py` 集中路径 + 环境变量覆盖（`AITC_*_PATH`）；后续可继续收敛其余散落路径 | 低 |
| C2（#10） | 流动窗口默认值易误解 | `DEFAULT_FLOW_DURATION_SECONDS=300` 与运行配置 150 不一致（运行时会被注入覆盖） | 去默认值（必填）或注明"仅占位" | 低 |
| C3（#9） | 两套 JSON 存储实现 | `lib/_local_json_store.py` 与 `infra/data/storage.py::JsonFileStore` 功能重复 | 只记录不合并（跨 lib 边界风险高） | 低 |
| C4（#8） | 遗留路径与服务 | `path_config.py`（62）+ 根目录 `time_schedule.py`（688，Flask）仅旧服务引用 | 确认无外部调用后移 `legacy/` | 中 |
| C5（#6/#7） | 根目录离线脚本混放 | 已核实（2026-10-01）：`intersection_to_rid_lambda.py`/`new_online_data_map_lambda.py` 是 `gen_online_config.py` 的生成产物，无导入方，已删除；`magic_hand.py` 零引用已删除；`config_check.py`/`gen_online_config.py`/`gen_api_docs.py` 为离线脚本 | 三个离线脚本移入 `tools/`（需补项目根目录 sys.path 修正），待做 | 低 |
| C6（#2） | 配置默认值单一来源 | ✅ 已完成：`RuntimeSettings` 字段默认值即唯一来源，`from_environment` 统一用 `cls.<字段>` 回退 | — | ✅ |
| C7（#3） | logs_data 默认参数 | 生产路径已全部显式注入 settings；默认值仅服务单测/独立脚本 | ✅ 保留占位默认 + 注释注明注入点 | ✅ |

## D. 算法与配置资产（后续再议，不改行为）

| # | 事项 | 现状 | 建议 | 优先级 |
| --- | --- | --- | --- | --- |
| D1 | `DQN_Select.py` 路口函数统一化 | 分发器 60+ if/elif 调用；**路口函数签名 4 种**（10 参：1300103/1300097/1300046/1300454/1300451/1300042 无 extend_map；11 参：大多数；12 参：1300870 含 overflowMap；14 参：1300271 含 overflowMap+radarMap）；函数模式 4 类（雷达数车 / 视频 predict_head / 流量 chuli_shuju / 空壳 [0]*10+select_pilot_schedule）；函数内大量 `print` 调试残留 | 分阶段：① 统一 15 参签名 + 分发改注册表 dict（纯机械、不改行为）；② SUB_*/device_no/分段线性阈值/Ng 上下限抽每路口配置表；③ 与 D5 合并为配置驱动的通用决策函数；④ 清理 print | 中（远期） |
| D2 | 绿波业务逻辑 | 由他人负责 | 暂不动，协同后处理 | — |
| D3 | online 数据提级到 DQN_select | 现状：纯互联网路口（133 个）不过 DQN，由协调模块 `process_internet_intersection` 全局处理；online 同时喂绿波走廊 | 将 online 作为 DQN 单路口输入（与 radar/video 同级），互联网路口纳入 DQN；算法行为大改，待系统成熟 | 高（远期） |
| D4 | 全局协调学习化 | 现状：绿波走廊链式规则传播（当前 1 条走廊 4 路口）+ 分类批量规则 + 共享规则（最小周期/浮动值）；非全图 GNN | 保留现状；成熟后升级为邻域学习式传播（仅与周边路口协调） | 低（远期） |
| D5 | 统一决策管线 | 现状：Cross_Video(65) 走「DQN→协调」；133 互联网路口不过 DQN 直接规则出方案；9 个路口无协调类别（7 个纯 DQN、2 个无任何处理） | 全路口统一「DQN 初版方案 → 类型化协调后处理」；需白名单扩展、回放对比、规则保留为 fallback；与 D3/D4 一并规划 | 高（远期） |
