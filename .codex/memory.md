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
- Pending: Continue project cleanup before the enterprise refactor, especially separating source, generated runtime data, configs, and tests.
- Next suggested step: audit tracked generated artifacts and remove any already-committed cache/log/build outputs from the index.

