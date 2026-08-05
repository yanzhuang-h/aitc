# Project Memory

- 2026-08-05: Began repository reset for planned enterprise refactor of AITC. Existing remote `origin` pointed to Gitee (`https://gitee.com/hu-zhuangyan/dkrg-aitc.git`) and was removed.
- Created new Git starting point on branch `main` using the current working tree snapshot. Initial commit message: `Initial project import for refactor`. Direct physical deletion/renaming of `.git` was blocked by Windows access permissions, so Git metadata was reset through Git commands instead.
- Added `.gitignore` for Python caches, virtual environments, build outputs, IDE files, local env files, logs, and temp files.
- Added `.gitattributes` to normalize text files to LF while keeping Windows scripts as CRLF.
- 2026-08-05: GitHub remote is now configured and `main` tracks `origin/main`. Added explicit `.gitignore` rules for recursive `__pycache__/` and `logs_data/` runtime output directories.
- 2026-08-05: Chose incremental refactor layout: keep `Agent/` as the agent layer, keep `infra/model/` as model-file storage only for now, and build the data foundation under `infra/data/`.
- Added initial `infra/data` repository modules for traffic records, config items, experience items, local JSON/JSONL persistence, window cache, receiver normalization, and a facade API.
- 2026-08-05: Read legacy data flow. `Server_AITC.py` currently mixes TCP intake, HTTP radar/config intake, window caches, periodic aggregation, DQN invocation, result packaging, and TCP broadcasting. Runtime data is classified by keys in `handle_individual_data`, cached in per-type deques, processed by `Process_cache_data.py`, logged through `Write_to_file.py`, and used by `Flow_predict.py`, `Queue_predict.py`, `time_schedule.py`, and `lib/DQN_Select.py`.
- 2026-08-05: Began component extraction without changing algorithms. Added `infra/data/classifier.py`, `runtime_cache.py`, `writer.py`, and `legacy_processor.py`; expanded `receiver.py` with `RuntimeDataReceiver`. These mirror legacy field classification, window durations, logging, and `Process_cache_data.py` calls so `Server_AITC.py` can later be thinned safely.
- 2026-08-05: Conda env available at `C:\Users\Finn\.conda\envs\aitc`. Wired `Server_AITC.py` input paths to `infra.data.classify_data` and `RuntimeDataWriter` while keeping legacy cache updates, radar event state, overflow warning state, periodic processing, and algorithm calls unchanged. Verified with `python -m compileall infra\data Server_AITC.py` and classifier sample assertions using that env.
- 2026-08-05: 将 `Server_AITC.py` 的运行期窗口缓存接入 `infra.data.RuntimeDataCache`，移除实际使用中的旧全局 deque 缓存。保留 `get_recent_*` 等旧函数名和返回形态，确保 `Process_cache_data.py` 与算法调用链不感知迁移。
- 2026-08-05: 将 TCP/HTTP 接收后的分类、写入、窗口缓存、雷达事件状态和溢出告警状态更新合并到 `infra.data.RuntimeDataReceiver`。`Server_AITC.py` 的 `handle_individual_data` 和 `handle_single_radar_data` 现在只做薄调用，传输层仍留在服务端入口中。
- 2026-08-05: 将 `process_data_to_send()` 的缓存快照读取与 `Process_cache_data.py` 聚合调用接入 `infra.data.LegacyCacheProcessor`。`Server_AITC.py` 不再直接导入 `Process_cache_data`，旧聚合函数仍保持不变。
- 2026-08-05: 将 `todo-done/8-5.md` 的数据底座开发部分整理为 checklist，记录已完成的 receiver/cache/writer/legacy_processor 抽象，并规划下一步收口 `Write_to_file.py`、配置接口、Nacos、time_schedule 和 Agent 查询工具。
- 2026-08-05: 收口 `Write_to_file.py` 的运行结果输出到 `infra.data.RuntimeDataWriter`，新增 `write_flow_prediction` 和 `write_queue_prediction`，并将 `Server_AITC.py` 中的 EXP、flow_pre、queue_pre、phase_check、send 写入全部切到数据底座门面。
- 2026-08-05: 进一步将 Write_to_file.py 的文件轮转启动也收口到 RuntimeDataWriter，主入口现在通过数据底座门面启动 start_filename_updater()。
- 2026-08-05: 抽出 `RuntimeDataIngestor` 作为 TCP/HTTP 协议接入门面，`Server_AITC.py` 的 65432 与 8088 入口现在在协议解析后统一进入 `RuntimeDataReceiver` 的 `ingest -> classify -> persist -> cache/state update` 管线.
- 2026-08-05: 新增 `ResultWarehouse` 和 `ResultSender`。周期处理线程只替换最新结果，广播线程通过结果仓库快照调用纯发送器；发送日志也由发送器统一写入。当前结果仓库使用线程安全内存实现，后续可替换为 Redis、文件或数据库。
- 2026-08-05: 新增 `infra/data/config.py` 的 `ConfigService` 配置服务门面。`Server_AITC.py` 不再直接依赖 `lib/config_api.py`，现有 `/road_info`、`/cross_info` 路由和旧 JSON 文件锁逻辑保持不变；后续再迁移具体配置存储。
- 2026-08-05: 扩展 `ConfigService`，增加 `ConfigResource`、`query()` 和 `write()`，为 HTTP、Agent 及其他模块提供统一配置访问入口。目前资源覆盖 `road_info` 和 `cross_info`；`road_state`、`floating_value` 继续保留现有 Nacos/算法同步链路。
- 2026-08-05: `ConfigService` 接入 `road_state`、`floating_value` 的读取、校验、单条更新和整表替换能力；为浮动值配置补充公开只读函数。Nacos 仍复用旧模块函数，当前没有改变同步行为。
- 2026-08-05: 进一步将 `intersection_result_config` 和 `time_schedule` 接入 `ConfigService`。时段方案以单路口工作日/周末文件加 manifest 形式管理，属于配置服务；补充其公开读取函数，Nacos 同步流程保持不变。
- 2026-08-05: 新增 `ConfigSyncManager`，将 floating_value、intersection_result、road_state、time_schedule 四类 Nacos 同步任务的创建、启动和停止从 `Server_AITC.py` 收口到数据底座配置同步模块；同步协议和环境变量保持不变。
- 2026-08-05: 在 `infra/data/api.py` 新增 `RuntimeDataQueryService`，统一提供运行窗口、结果仓库和配置快照的只读查询；`Server_AITC.py` 以当前运行对象初始化该服务，雷达健康响应已通过此服务查询缓存大小。查询结果均为副本，后续可在保持接口不变的前提下切换 Redis/数据库。
- 2026-08-05: 新增 `RuntimeRecord` 和 `RuntimeRepository`，`RuntimeDataReceiver` 通过显式注入的 `DataRepository` 将已分类运行记录按 `DataKind` 写入 `infra/data/runtime/runtime/*.jsonl`，同时保留旧日志写入。`RuntimeDataQueryService` 可查询实时缓存和持久化历史；新增独立单元测试验证接收、缓存、持久化和查询链路。
- 2026-08-05: 运行数据仓库补充 `intersection_id`、`received_at` 字段，接收器优先读取数据中的路口字段，并可通过已注入的检测器映射解析 `jtll_ddbh`。历史查询支持路口和时间范围过滤；每类数据默认最多保留 10,000 条，裁剪采用原子 JSONL 替换。单元测试覆盖保留策略和过滤查询。
- 2026-08-05: 手工 TCP/HTTP 回放客户端和自动化数据底座测试统一整理到 `test/`，避免重复测试目录。后续集成验证优先复用 `test/client_tcp.py` 和 `test/client_http.py`，自动化测试通过 `python -m unittest discover -s test -p "test_*.py"` 运行。
- 2026-08-05: 将 `Agent/` 目录统一重命名为小写 `agent/`；当前保留 `qwen_agent.py` 与 `tools.py` 作为后续 Agent 开发入口。
- 2026-08-05: 在 `agent/tools.py` 新增框架无关的 `DataQueryTools`。它为 Agent 提供实时数据、历史数据、最新结果和配置快照四类只读查询，统一返回 `status`、`summary`、`data`、`meta`，并限制单次记录数为 100。Qwen 接入层可使用 `tool_schemas()` 和 `invoke()`；测试覆盖工具契约、错误结构和参数限制。
- 2026-08-05: 暂缓 Qwen 运行时接入，优先优化可独立测试的工具和数据仓库。`DataQueryTools` 新增默认 `summary` 与显式 `full` 详情级别，避免模型上下文被原始记录占满；运行记录写入和时间范围查询均规范为 UTC。自动化测试扩展至 7 项。
- 2026-08-05: 在 `agent/qwen_agent.py` 实现不依赖 Qwen SDK 的 `SymbolicDataAgent`。它将四类显式动作路由到已声明的只读数据工具，拒绝未授权动作。新增完整链路测试：接收 TCP 风格数据 -> 分类/缓存/JSONL 仓库 -> 查询服务 -> 工具 -> 符号 Agent；当前自动化测试共 9 项通过。
- 2026-08-05: 修复最小回放数据缺少 `ts`/`start_time` 时周期线程被旧预测写入中断的问题。新增 `is_millisecond_timestamp()`；无有效毫秒时间戳时仅跳过 flow/queue 预测文件写入，继续执行接收、缓存、仓库和后续决策链路。自动化测试增至 11 项。
- 2026-08-05: 优化 `test/client_tcp.py` 的定时回放流程：新增 `--start-timestamp`，定时发送会在最后一个实际数据时间点自动结束。新增完整 flow 样本 `test/fixtures/flow_replay.jsonl` 和回放客户端测试；自动化测试增至 14 项。
- 2026-08-05: 在 `todo-done/data-flow-baseline.md` 固化当前端到端调用链：TCP/HTTP -> 数据底座 -> 旧聚合适配 -> `lib.DQN_Select` 路口策略 -> 全局协调/相位校验 -> 结果仓库/广播。后续应先抽取不改算法的周期决策管线，再精简服务启动文件。
- 2026-08-05: 新增 `runtime.PeriodicDecisionPipeline`，由 `Server_AITC.py` 注入数据底座、预测模块、既有 `lib` 算法和结果仓库。服务启动线程已切换到新管线；旧周期函数暂留作未运行的回退代码，待下一次回放确认后删除。新增管线隔离测试，自动化测试共 15 项。
- 2026-08-05: 已使用 `test/fixtures/flow_replay.jsonl` 完成新周期决策管线的真实 TCP 回放。记录写入 `infra/data/runtime/runtime/flow.jsonl`，周期线程完成 flow 聚合、预测与相位校验，后台日志未出现 ERROR/Traceback；验证服务已停止。下一步可删除 `Server_AITC.py` 中未运行的旧周期编排函数。
- 2026-08-05: 删除 `Server_AITC.py` 中已被 `PeriodicDecisionPipeline` 替代的旧路口处理、旧聚合和旧周期函数，主文件减少约 180 行；同步移除无效的协调状态与线程池全局变量。保留 TCP/HTTP 接收、广播与服务生命周期代码。
- 2026-08-05: 抽取 `runtime.TcpRuntimeServer`，接管 TCP 65432 的监听、换行 JSON 解析、`RuntimeDataIngestor` 调用、客户端连接管理和结果广播。`Server_AITC.py` 仅装配并启动该服务。新增 TCP 服务单元测试；真实 flow 回放确认数据写入与周期 flow 聚合正常，日志无 ERROR/Traceback，验证服务已停止。自动化测试共 17 项。
- 2026-08-05: 新增 `runtime.HttpRuntimeServer`，接管 HTTP 8088 的雷达/博研接收、配置转发、健康检查和安全响应头；`Server_AITC.py` 已切换到新服务。新增本地 HTTP 自动化测试，当前共 19 项通过。旧 HTTP handler 暂留作未运行回退代码，待真实回放后删除。
- 2026-08-05: 已对新 HTTP 服务执行真实 `POST /radar` 回放，返回成功，HTTP 来源 radar 数据写入 `infra/data/runtime/runtime/radar.jsonl`，后台日志无 ERROR/Traceback，验证服务已停止。下一步删除主文件中的旧 HTTP 实现。
- 2026-08-05: 删除 `Server_AITC.py` 中已被 `HttpRuntimeServer` 替代的旧 HTTP handler、CORS/安全响应常量、跨域判断与启动函数，主文件减少约 230 行。TCP、HTTP 与周期决策现均由 `runtime/` 组件承载；自动化测试共 19 项通过。
- 2026-08-05: 新增 `runtime.AITCApplication` 与 `create_application()`，集中装配 TCP/HTTP 服务、周期决策、预测调度和配置同步，并统一管理启动、停止和可中断的周期线程。`Server_AITC.py` 现仅保留日志配置、信号绑定和 `application.run()`；新增生命周期测试，自动化测试共 20 项。
- 2026-08-05: 将 `RuntimeDataWriter` 对旧 `Write_to_file.py` 的运行依赖替换为 `FileRuntimeOutputStore`。新本地输出仓库保持 `logs_data/<category>/<date>_<category>.txt` 与 `logs_data/EXP/<intersection>/EXP_<timestamp>.json` 格式；新增输出兼容测试。使用 flow fixture 启动完整服务并 TCP 回放后，确认 `flow`、`flow_pre`、`phase_check` 与 EXP 输出更新，后台无 `ERROR`/`Traceback`，验证服务已停止；自动化测试共 22 项通过。
- 2026-08-05: 清理旧输出模块 `Write_to_file.py`。运行代码已无任何引用；同步移除 `RuntimeDataWriter`、`FileRuntimeOutputStore` 和应用装配中的无效文件名轮转线程调用。输出仍由 `FileRuntimeOutputStore` 按写入时日期直接定位，自动化测试 22 项与编译检查均通过。
- 2026-08-05: 将根目录 `Process_cache_data.py` 迁入 `infra/data/cache_processor.py`，并将缓存聚合门面从 `LegacyCacheProcessor`/`legacy_processor.py` 重命名为 `RuntimeDataProcessor`/`runtime_processor.py`。周期决策管线依赖名称同步改为 `data_processor`；未改变聚合算法或 `lib` 调用。同步更新数据底座 README、数据流基线和 checklist；自动化测试 22 项与编译检查均通过。
- 2026-08-05: 新增 `test/test_cache_processor.py` 作为运行数据聚合行为基线，覆盖 flow、queue、stage、extend、online、radar、boyan 的最小输入输出契约。当前自动化测试共 27 项通过，编译检查通过；下一步可在此测试保护下，将 `cache_processor.py` 对全局 `Lambdas` 的依赖改为显式注入。
- 2026-08-05: 完成聚合组件的配置依赖解耦。`infra/data/cache_processor.py` 不再导入全局 `Lambdas`，由 `RuntimeDataProcessor` 接收并向各聚合函数传递配置模块，`runtime.create_application()` 负责装配该依赖。聚合行为基线测试与全量自动化测试共 27 项通过，编译检查通过。
- 2026-08-05: 将根目录 `Select_data_to_send.py` 迁入 `runtime/result_formatter.py`，作为周期决策到下游控制报文的输出适配器。格式化器通过应用装配层使用 `partial` 显式注入 `Lambdas`，周期管线接口不变；新增报文结构测试。全量自动化测试共 28 项通过，编译检查通过。
- 2026-08-05: 将流量、排队预测任务的 APScheduler 生命周期从 `Flow_predict.py`、`Queue_predict.py` 收口到 `runtime/prediction_scheduler.py`。`AITCApplication` 统一启动和停止调度器，预测模块保留计算与读写逻辑；新增调度注册和停止测试。全量自动化测试共 29 项通过，编译检查通过。
- 2026-08-05: 新增 `infra/data/prediction_repository.py` 的 `FilePredictionRepository`，统一读取 flow/queue 历史样本与保存、查询每日预测 JSON。仓库优先采用当前 `logs_data/<category>/` 输出布局，同时兼容旧根目录文件；`runtime/prediction_service.py` 将该仓库显式注入两个预测算法，周期决策和每日调度共用同一实例。全量自动化测试共 31 项通过，编译检查通过。
- 2026-08-05: 建立运行数据契约基线。`infra/data/contracts.py` 定义 flow、queue、stage、雷达等 11 类数据的来源、最小字段、时间和路口识别规则，`todo-done/data-contract.md` 记录中文契约表；校验为非阻断式以兼容旧链路。新增契约测试后全量自动化测试共 34 项通过，编译检查通过。
- 2026-08-05: 新增 `infra/data/ports.py`，定义运行历史、预测与结果存储的 Protocol 端口；预测运行服务已按 `PredictionStore` 依赖，为后续 Redis/数据库实现保留替换边界。预测相关测试与编译检查通过。
- 2026-08-05: 新增 `DataQualityMonitor`，`RuntimeDataReceiver` 在分类后执行非阻断式契约校验并记录问题；查询服务及 HTTP 健康响应暴露累计数量、分类统计与近期问题。数据照常持久化、缓存和参与旧算法。全量自动化测试共 35 项通过。
- Pending: Continue project cleanup before the enterprise refactor, especially separating source, generated runtime data, configs, and tests.
- Next suggested step: 盘点根目录剩余的数据处理与预测模块，区分算法实现和运行编排职责，再决定下一批可迁入 `runtime/` 或 `infra/data/` 的边界。





