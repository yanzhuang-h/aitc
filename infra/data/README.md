# 数据底座

`infra/data` 是 AITC 的独立数据底座，负责运行数据的接收、分类、缓存、持久化、聚合和查询，并为 Agent 与决策运行层提供稳定接口。

## 当前职责

- `ingest.py`、`receiver.py`：统一接入 TCP/HTTP 完成协议解析后的数据。
- `classifier.py`：按现有字段规则识别运行数据类型。
- `runtime_cache.py`：维护各类数据的内存时间窗口。
- `repository.py`、`api.py`：持久化运行记录并提供只读查询。
- `output_store.py`、`writer.py`：将运行输出写入兼容的 `logs_data` 文件结构。
- `cache_processor.py`：在不改变算法逻辑的前提下，将窗口数据聚合为既有算法所需结构。
- `runtime_processor.py`：连接 `RuntimeDataCache` 与聚合函数，作为决策管线的数据处理入口。
- `result_warehouse.py`、`result_sender.py`：保存最新结果并负责向客户端发送。
- `config.py`、`config_sync.py`：提供配置访问与配置同步边界。

运行记录默认写入 `infra/data/runtime/`，运行日志默认写入 `logs_data/`；两者均为本地产物，不提交到 Git。
