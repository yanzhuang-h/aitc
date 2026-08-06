# 数据底座

`infra/data` 是 AITC 的独立数据底座，负责数据接入、分类、短期记忆、长期记忆、结果仓库和统一查询。

## 记忆层

- `memory/shorttermmemory.py`：短期记忆，保存带时间窗口的实时运行数据。当前使用线程安全内存实现，不绑定 Redis。
- `memory/longtermmemory.py`：长期记忆，保存运行历史、配置和经验数据。当前使用 JSON/JSONL 文件实现，不绑定具体数据库。
- `memory/memoryquerylayer.py`：统一查询层，为 Agent、HTTP 健康接口和运行决策提供只读查询。
- 记忆模块只从 `infra.data.memory` 或 `infra.data` 的公共导出访问，避免维护重复兼容入口。

## 数据工具组件

- `ingest.py`、`receiver.py`：统一接收 TCP/HTTP 协议解析后的数据。
- `classifier.py`、`contracts.py`：数据分类和契约校验。
- `repository.py`：长期记忆当前使用的文件存储实现。
- `runtime_processor.py`、`cache_processor.py`：将短期记忆快照适配为既有算法输入。
- `result_warehouse.py`、`result_sender.py`：保存最新结果并负责向客户端发送。
- `config.py`、`config_sync.py`：配置访问与配置同步边界。

这些组件按接入、校验、存储、处理和输出职责组织在 `infra/data` 中；它们是记忆层的工具实现，不承担长短期记忆语义。

## 设计原则

短期记忆和长期记忆表达的是数据生命周期语义，而不是数据库类型。未来可以在不修改接收器、Agent 和查询层的情况下，将底层实现替换为 Redis、SQLite、PostgreSQL 或其他存储。

运行记录默认写入 `infra/data/runtime/`，运行日志写入 `logs_data/`。这些本地产物不提交到 Git。
