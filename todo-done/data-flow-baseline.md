# 当前数据链路基线

本文记录 2026-08-05 回放验证后的实际数据链路。它是后续模块化 `Server_AITC.py` 的依据，不改变现有算法与 `lib/` 内实现。

## 1. 启动与边界

- `Server_AITC.py:start_server()` 启动 Nacos 配置同步、HTTP 8088 服务、周期处理线程、结果广播线程和 TCP 65432 服务。
- TCP 65432 同时承担数据上报和结果订阅：连接建立后被加入 `clients`，接收数据的同时也会接收结果广播。
- HTTP 8088 接收雷达/博研数据，同时提供配置接口和健康检查。
- `agent/` 当前只读查询 `infra/data`，不参与实时控制决策。

## 2. 接收、分类与存储

### TCP 65432

`handle_client()` 按换行读取 JSON -> `preprocess_data()` 展开对象或列表 -> `handle_individual_data()` -> `RuntimeDataIngestor.ingest_tcp_item()`。

### HTTP 8088

`RadarHTTPRequestHandler.do_POST()` 解析 JSON -> `process_radar_data()` -> `handle_single_radar_data()` -> `RuntimeDataIngestor.ingest_http_item()`。

### 统一数据管线

两种协议进入 `RuntimeDataReceiver.receive()` 后，统一执行：

`classify_data` -> `RuntimeDataWriter.write` -> `DataRepository.store_runtime_data` -> `RuntimeDataCache` 或雷达事件状态更新。

- `RuntimeDataWriter` 通过 `FileRuntimeOutputStore` 写入兼容的日志目录结构。
- `DataRepository` 将标准记录写入 `infra/data/runtime/runtime/<kind>.jsonl`，供历史查询使用。
- `RuntimeDataCache` 维护实时窗口。当前窗口为：flow 600 秒、queue 240 秒、stage/extend/radar/boyan 600 秒、online/latest 1800 秒。
- overflow warning 与 radar event 不进入普通窗口，而是更新 `overflowWarningMap`、`radar_event_map`。

## 3. 周期聚合与算法输入

`periodic_data_processing()` 每 `SEND_INTERVAL`（当前 50 秒）执行一次 `process_data_to_send()`：

1. `RuntimeDataProcessor.snapshot()` 从 `RuntimeDataCache` 取得各类型窗口快照。
2. `RuntimeDataProcessor` 调用 `cache_processor.py`，将实时记录转为算法仍需要的结构。
3. 聚合结果包括：
   - `process_flow_data`：`intersection_flow`、按秒 `flow_map`，依赖 `jtll_ddbh`、`ycsb_cdbh`、`ts`。
   - `process_queue_data`：`result_queue_length`、按秒 `queue_map`，依赖 `jtll_ddbh`、`start_time`、`car_nums`。
   - `process_stage_data`、`process_extend_data`、`process_online_data`、`process_radar_data`、`process_boyan_data`：形成各自的路口映射。
   - `process_radar_event_data`：组合雷达事件与溢出告警状态。
4. 流量/排队窗口有有效毫秒时间戳时，分别调用 `Flow_predict.flow_pre_json_Gen()`、`Queue_predict.queue_pre_json_gen()` 写出预测日志；时间戳缺失时只跳过该日志输出，不中断决策。
5. `Flow_predict.get_current_flow_prediction()` 和 `Queue_predict.get_current_queue_prediction()` 读取已调度的预测结果，作为 DQN 的附加输入。

## 4. lib 算法调用链

`process_data_to_send()` 为 `Lambdas.intersection_list` 中每个路口并行调用 `process_single_intersection()`。

每个路口会从全局聚合映射中切出本路口数据，再调用：

`lib.DQN_Select.DQN_select(traffic_vector, queue_vector, traffic_vector_duration2, current_time, flow_map, queue_map, stage_map, last_coordinate_set, flow_prediction, queue_prediction, extend_map, radar_event_map, radar_map, intersection_id, boyan_map)`。

- `DQN_select` 以 `cross_id` 分派到具体的 `DQN_select_<路口编号>` 函数。
- 这些专用函数调用 `lib.AITC_tool`、`lib.cha`、`lib.cha1` 等已有策略/模型工具；个别路口还使用 `chuli_shuju`。
- `Lambdas.py` 提供检测器、车道、路口、方向和默认结构映射，是聚合与算法输入的共同字典基座。
- 每个路口算法返回 `result_action`、`coordinate_map`、`model_info_list`、`EXP_list`；EXP 由 `RuntimeDataWriter.write_experience()` 输出。

## 5. 决策收敛与结果发送

1. 所有路口结果完成后，`last_coordinate_set` 更新为本轮 `coordinate_map`。
2. `lib.Global_intersection_coordinate.coordinate()` 根据相邻路口协调信息、online 数据和溢出状态修正全局动作；该函数内部还会应用 `lib.floating_value.apply_floating_value()` 与道路状态规则。
3. `phase_check.phase_check()` 用 `intersection_result_config.json` 限制各相位时长，并生成校验报告。
4. `Select_data_to_send.select_data_to_send()` 将动作、流量向量和模型信息打包为下发协议。
5. `ResultWarehouse.replace()` 原子替换内存中的最新结果集。
6. `broadcast_results()` 从结果仓库取快照，调用 `ResultSender.send_batch()` 向所有 TCP 客户端逐条发送 JSON，并通过 `RuntimeDataWriter` 记录发送日志。

## 6. 当前结论与后续拆分边界

- 数据底座已独立承担接收、分类、实时缓存、运行记录持久化、查询和结果仓库职责。
- 聚合和 `lib/` 算法仍是兼容边界：`RuntimeDataProcessor` 将底座缓存转换成既有算法需要的输入，当前不应改动算法实现。
- `Server_AITC.py` 仍承担协议服务、周期调度、跨路口编排、全局后处理和客户端管理；这正是下一阶段要拆出的应用编排层。
- 周期决策管线已完成抽取，保留对 `RuntimeDataProcessor`、`DQN_select`、`coordinate`、`phase_check` 和 `ResultWarehouse` 的显式依赖；`Server_AITC.py` 只负责启动和停止。

## 7. 真实数据回放验证（2026-08-10）

用 `test/client_tcp.py` 回放运维提供的真实数据（`test/flow_data`、`test/extend_data`、`test/online_data`），验证数据底座与决策链路：

1. **回放客户端修复**：`--start-timestamp` 参数支持从指定时间戳定位起点（此前硬编码 6-29 起点，导致 7-29 数据全部被过滤）；`_run_timed_enhanced` 改为在窗口内只遍历实际存在的时间点、发完即止（此前按 `duration_sec` 空转）。
2. **回放结果**：
   - flow（2026-07-29，300s 窗口）：发送 2470 条 → `flow.jsonl` 714KB
   - extend（2026-07-29，300s 窗口）：发送 18928 条 → `extend.jsonl` 2.85MB
   - online（2026-05-14，round_robin preload 5000）：发送 5000 条 → `online.jsonl` 150KB
3. **决策消费**：下一周期决策日志中 `result_action`/`traffic_vector`/`model_info_list` 由空数据全 0 变为真实值（如 `traffic_vector: [24, 32, 6, 5]`），证明 接收 → 分类 → 落盘 → 聚合 → DQN 决策全链路打通。
4. **回归**：全量测试 93 项通过（含回放客户端 3 项）。

