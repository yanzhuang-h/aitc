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
- Pending: Continue project cleanup before the enterprise refactor, especially separating source, generated runtime data, configs, and tests.
- Next suggested step: 为运行数据、结果和配置定义面向 Agent 的只读工具契约与返回摘要格式。





