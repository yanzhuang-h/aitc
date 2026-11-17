# 调整候选清单（Backlog）

> 汇总学习 Day 1（入口/装配/协议）与 Day 2（数据底座 `datahub`）过程中发现的、待后续统一处理的调整点，避免遗漏。
> 已落地的事项不入此表（见各 PR）；每项注明来源、现状、建议与优先级（低/中/高）。
> 处理原则：先小后大、行为不变优先；涉及算法行为的事项需单独说明影响面。

当前优先交付19/49组修复与诊断，1700125为重点样例；更早历史路口统一迁移暂缓。
另一条主线采用原生AgentScope的Workflow与Agent Loop。下列旧候选仅供筛选，不代表本轮全部实施。
生产材料仅在对应任务实际推进且现有证据不足时补取。

## A. 架构与模块化

| # | 事项 | 现状 | 建议 | 优先级 | 边界 | 生产配合及用途 |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | HTTP 服务拆分 | `runtime/http_server.py`（539 行，约 30 个路由）一锅端：雷达/博研数据收取 + 前端页面 + 配置 + Agent + 绿波 + 健康检查 | 数据收取（雷达/博研）与 TCP 同级；其余管理面服务单开文件（方向：FastAPI，Day 1 已定） | 高（后期集中做） | 本地实现、生产验收 | 复用接口样例；上线核对原HTTP/TCP调用和连接日志 |
| A2 | 存储升级路线 | 短窗=内存 deque；长仓=JSONL；结果仓=内存列表 | 短窗→Redis；长仓→SQLite（首选）；结果仓→Redis；只动三个实现文件，调用方零改动 | 中（视部署规模） | 需生产数据（按需） | 先取得存储增长、读写延迟和积压证据，确认是否值得更换存储 |
| A3 | 两套写入收敛 | `logs_data/*.txt`（人读兼容 + 补 `AITC_SYS_TS`）与 `runtime/*.jsonl`（程序查）并存 | `runtime/*.jsonl` 做唯一真相源，`logs_data` 降级为兼容视图；先盘点消费者（flow_pre/queue_pre 预测、EXP、现场人工）再迁移；不换 YAML | 中 | 本地实现、生产验收 | 核对预测、训练及现场日志消费者，验证兼容输出未缺失 |
| A4 | 配置资源同步来源抽象 | 4 类走 Nacos（floating_value/intersection_result/road_state/time_schedule），2 类走 HTTP 文件（road_info/cross_info）；`ConfigService` 门面已收口 | 暂不抽"同步源接口"（YAGNI）；出现第二类配置中心再抽象 | 低 | 本地可完成（暂不抽象） | 无需新增材料；保留现有Nacos/HTTP来源 |
| A5 | 接入层吞吐优化 | TCP 65432 + HTTP 8088 分端口：信控平台走 TCP（长连接、量最大），雷达/博研走 HTTP；旧原因="一个端口忙不过来" | 协议拆分保留（设备协议决定）；方向：异步接收/独立写线程池，或统一网关+消息队列（MQ）；按规模再定 | 中 | 需生产数据（按需） | 先提供吞吐、积压和耗时证据，定位真实瓶颈 |
| A6 | Agent 层重构（需求驱动） | 现状：五类组件叠加（SymbolicDataAgent / QwenSignalTimingAgent / QwenToolRouterAgent / ControlProcessAgent / AgentHarness）+ 双路由（IntentRegistry + action 符号路由）+ 15 个意图（绿波占 9 个，实为资源 CRUD）；工具需四处声明；文件命名不清晰（qwen_agent.py 一文件三类、tools.py 泛指） | 按原生AgentScope重建Workflow与Agent Loop结合的诊断入口；复用现有数据和算法工具，完成调用迁移后移除旧LangGraph编排及冗余路由；保持固定配时独立运行和现有接口兼容 | 中（远期） | 本地可完成 | 原生AgentScope迁移与诊断首版使用本地数据和模型桩；现场建议效果另验收 |
| A7 | 目录与模块结构重构 | 现状：根目录混放运行入口与离线脚本；`app/core/tools` 反向依赖 `agents.registry`；`lib` 内分域不完全；`agents` 与运行时装配耦合 | 参照成熟分层惯例（FastAPI 风格 `app/{api,core,models,services}` 或 domain/application/infrastructure）+ `架构.png` 模块边界（数据底座/控制模块/安全引擎）分步调整；先收敛根目录（C4/C5）、注册中心下沉、lib 分域、agents 服务化；不照搬图，逐项迭代 | 中（远期） | 本地可完成 | 以调用与测试证据整理边界，不因目录形式整体重写 |
| A8 | MCP 多服务器化 | 现状：单个 `agents/mcp_server.py` 暴露全部 10 个工具 | 按功能域拆多个 MCP server（数据查询 / 信号控制 / 绿波管理等），各自独立进程与配置；复用统一注册中心按域过滤 | 低（远期） | 本地可完成（暂不拆分） | 有真实隔离需求后再拆，当前无需生产材料 |

## B. 数据底座待办

| # | 事项 | 现状 | 建议 | 优先级 | 边界 | 生产配合及用途 |
| --- | --- | --- | --- | --- | --- | --- |
| B1 | 内部时间归一化 `event_ts` | `ts/time/start_time/createTime` 名字各异（上游协议决定），转换散落在 `cache_processor.process_*`（flow/queue/stage 毫秒//1000，radar/boyan `int(ts)`，extend/online/latest 用到达时间） | receiver 落库前补统一 `event_ts`，不动 payload | 中 | 本地分析、需生产语义 | 确认各时间字段的单位、时钟来源及到达/事件含义 |
| B2 | 无调用方清理 | `heartbeat` 无任何消费者（仅 debug 日志+入库）；`receive_many`/`ingest_*_item` 全仓无调用方；`DataContract.intersection_fields` 无读者；`DataKind.UNSUPPORTED` 无生产者 | 逐个确认后删除或注释标注；heartbeat 可考虑做成"设备在线状态表" | 低 | 本地可完成 | 确认调用与协议用途后清理；不因暂无决策消费者删除原始证据 |
| B3 | radar 长期记录路口为空 | 解析器不认 `deviceNo`，`intersection_id` 恒 null；窗口却靠 `device_to_location` 把关，两路径不对称 | 确认语义后补解析或文档说明 | 低 | 本地分析、需生产语义 | 复用deviceNo和路口映射样例，核对雷达归属 |
| B4 | radar_event 三类事件无消费者 | 四类事件仅 `OverFlow` 进决策，`QueueOverrun/Parking/Speeding` 只收不用 | 确认占位还是补处理（属算法行为，单独评估） | 中 | 需生产语义 | 确认事件含义和期望控制行为后再接入 |
| B5 | `latest` 无决策消费者 | 快照里有、决策不读 | 确认语义或清理 | 低 | 本地分析、需生产语义 | 确认latest的业务用途及外部消费者 |
| B6 | `schemas.py` 注释中文化 | 顶部与部分 docstring 为英文，与全仓中文约定不一致 | 统一中文 | 低 | 本地可完成 | 无需生产材料 |
| B7 | `read_jsonl` 无逐行容错 | 坏行直接抛（现状靠写端保证） | 可选加固 | 低 | 本地可完成（按需） | 仅在真实坏行影响读取时修复，不预建额外容错链 |
| B8 | 广播断连半包 | `ResultSender` 逐条 `sendall`，断连客户端可能收到半包 | 接收端按 `\n` 分帧已兜底，保持旧行为，仅记录 | 低 | 本地可完成 | 本地模拟断连；现场仅核对发送计数与断连日志 |
| B9 | CONTRACTS 条目 kind 重复 | 字典键与构造首参各写一遍 | 可选收敛（小冗余） | 低 | 本地可完成 | 无需生产材料，保持契约格式 |
| B10 | 字段字典待核实项 | `ycsb_cpzxd`、`rid`、`distance`、`carNums`、`car_nums[].queue/all` 为推断；`ycsb_xsfx` 编码与 `ycsb` 前缀待确认 | 后续对照飞书文档/数据核实，扩展为详尽版字典 | 低 | 需生产语义 | 按具体字段补协议定义和样例，避免推断成为默认规则 |
| B11 | Lambdas 资产整理 | `Lambdas.py`（3392 行）集中映射字典、结构模板与内联配置大表；命名不统一（`aibi_to_xinkongji`、`huawei_device_to_location` 等拼音）；部分资产与 `lib/*.json` 重复 | 拆分 json 资产、规范化英文命名、去重；只动组织方式，不动算法语义 | 低 | 本地实现、生产验收 | 当前只处理19/49组相关共性组织问题；历史映射行为保持 |
| B12 | 存量拼音命名改造 | 2026-11-14 首批完成：cha → cycle_experience_timing、cha1 → movement_experience_timing、lvbotest → green_wave_coordination；旧模块路径保留为同一模块实例的兼容别名，避免状态分裂。其余 ti、tong_yong_biao、buqi_new2.0、data_chou、E_T_new 及拼音函数名仍待分类整理 | 后续继续按职责分批迁移；DQN_Select 与 Global_intersection_coordinate 的改名须同步上架脚本、静态审计和打包入口；不混入算法行为修改 | 低 | 本地可完成 | 引用、兼容导入和工具入口回归，无需新增现场数据 |

## C. 配置抽象（路线微调候选，未落地项）

| # | 事项 | 现状 | 建议 | 优先级 | 边界 | 生产配合及用途 |
| --- | --- | --- | --- | --- | --- | --- |
| C1（#4） | 配置文件路径硬编码 | `control/synergy/green_wave_api_adapter.py`、`phase_check.py`、`time_schedule/get_sch_for_cross.py` 写死路径 | ✅ 已落地：`app/paths.py` 集中路径 + 环境变量覆盖（`AITC_*_PATH`）；后续可继续收敛其余散落路径 | 低 | 本地可完成 | 已完成部分保持；剩余路径按调用方验证 |
| C2（#10） | 流动窗口默认值易误解 | `DEFAULT_FLOW_DURATION_SECONDS=300` 与运行配置 150 不一致（运行时会被注入覆盖） | 去默认值（必填）或注明"仅占位" | 低 | 本地可完成 | 复用运行配置与测试确认注入，无需生产材料 |
| C3（#9） | 两套 JSON 存储实现 | `lib/_local_json_store.py` 与 `datahub/storage.py::JsonFileStore` 功能重复 | 只记录不合并（跨 lib 边界风险高） | 低 | 本地可完成（暂不合并） | 出现实际重复维护问题时再处理 |
| C4（#8） | 遗留路径与服务 | ✅ 已完成（2026-11-06）：根目录 `time_schedule.py`（旧 Flask 服务，长期被同名 `time_schedule/` 包遮蔽）与 `path_config.py` 已移入 `legacy/`；`path_config.PROJECT_ROOT` 按新位置修正，`time_schedule/get_time_tools.py`（当前无调用方）改为从 `legacy.path_config` 导入 | 运行链路径统一由 `app/paths.py` 负责 | 中 | 本地已完成 | 无需现场验收 |
| C5（#6/#7） | 根目录离线脚本混放 | ✅ 已完成（2026-11-06）：`config_check.py`、`gen_online_config.py`、`gen_api_docs.py` 已移入 `tools/`，补齐仓库根目录 sys.path 与文档输出路径，生成产物加入 `.gitignore`；`intersection_to_rid_lambda.py`/`new_online_data_map_lambda.py`、`magic_hand.py` 此前已删除 | 新增离线脚本一律放 `tools/`，用法见 `tools/README.md` | 低 | 本地已完成 | 无需现场验收 |
| C6（#2） | 配置默认值单一来源 | ✅ 已完成：`RuntimeSettings` 字段默认值即唯一来源，`from_environment` 统一用 `cls.<字段>` 回退 | — | ✅ | 本地已完成 | 无需现场验收 |
| C7（#3） | logs_data 默认参数 | 生产路径已全部显式注入 settings；默认值仅服务单测/独立脚本 | ✅ 保留占位默认 + 注释注明注入点 | ✅ | 本地已完成 | 无需现场验收 |

## D. 算法与配置资产（后续再议，不改行为）

| # | 事项 | 现状 | 建议 | 优先级 | 边界 | 生产配合及用途 |
| --- | --- | --- | --- | --- | --- | --- |
| D1 | `DQN_Select.py` 路口函数统一化 | 分发器 60+ if/elif 调用；**路口函数签名 4 种**（10 参：1300103/1300097/1300046/1300454/1300451/1300042 无 extend_map；11 参：大多数；12 参：1300870 含 overflowMap；14 参：1300271 含 overflowMap+radarMap）；函数模式 4 类（雷达数车 / 视频 predict_head / 流量 chuli_shuju / 空壳 [0]*10+select_pilot_schedule）；函数内大量 `print` 调试残留 | 分阶段：① 统一 15 参签名 + 分发改注册表 dict（纯机械、不改行为）；② SUB_*/device_no/分段线性阈值/Ng 上下限抽每路口配置表；③ 与 D5 合并为配置驱动的通用决策函数；④ 清理 print | 中（远期） | 本地实现、生产验收 | 49组公共入口已完成；继续处理19/49组，历史其他路口暂缓 |
| D2 | 绿波业务逻辑 | 由他人负责 | 暂不动，协同后处理 | — | 需对方协作（暂缓） | 明确绿波业务负责人和验收规则 |
| D3 | online 数据提级到 DQN_select | 现状：纯互联网路口（133 个）不过 DQN，由协调模块 `process_internet_intersection` 全局处理；online 同时喂绿波走廊 | 将 online 作为 DQN 单路口输入（与 radar/video 同级），互联网路口纳入 DQN；算法行为大改，待系统成熟 | 高（远期） | 暂缓历史迁移 | 以后取得互联网输入、原控制输出与现场规则后再议 |
| D4 | 全局协调学习化 | 现状：绿波走廊链式规则传播（当前 1 条走廊 4 路口）+ 分类批量规则 + 共享规则（最小周期/浮动值）；非全图 GNN | 保留现状；成熟后升级为邻域学习式传播（仅与周边路口协调） | 低（远期） | 暂缓历史迁移 | 以后确认邻域数据与协调效果验收方式 |
| D5 | 统一决策管线 | 现状：Cross_Video(65) 走「DQN→协调」；133 互联网路口不过 DQN 直接规则出方案；9 个路口无协调类别（7 个纯 DQN、2 个无任何处理） | 全路口统一「DQN 初版方案 → 类型化协调后处理」；需白名单扩展、回放对比、规则保留为 fallback；与 D3/D4 一并规划 | 高（远期） | 暂缓历史迁移 | 当前仅整合19/49组，更早历史路口不在本轮切换 |
