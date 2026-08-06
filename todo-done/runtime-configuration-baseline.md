# 运行配置基线

## 统一入口

`app/config.py` 中的 `RuntimeSettings` 是当前运行配置的唯一集中入口。它暂时使用标准库读取环境变量，避免在架构迁移早期增加 `pydantic-settings` 依赖；未来可在不修改调用方的情况下替换实现。

## 当前配置清单

| 配置项 | 环境变量 | 旧默认值 | 当前用途 |
| --- | --- | --- | --- |
| TCP 主机 | `AITC_TCP_HOST` | `127.0.0.1` | TCP 数据接收与结果广播。 |
| TCP 端口 | `AITC_TCP_PORT` | `65432` | TCP 监听端口。 |
| TCP 缓冲区 | `AITC_TCP_BUFFER_SIZE` | `1048576` | 单次 socket 读取大小。 |
| HTTP 主机 | `AITC_HTTP_HOST` | `127.0.0.1` | 雷达和配置 HTTP 服务。 |
| HTTP 端口 | `AITC_HTTP_PORT` | `8088` | HTTP 监听端口。 |
| 决策周期 | `AITC_DECISION_INTERVAL_SECONDS` | `50` 秒 | 周期决策管线执行间隔。 |
| 广播周期 | `AITC_RESULT_SEND_INTERVAL_SECONDS` | `50` 秒 | 最新控制结果广播间隔。 |
| 流量窗口 | `AITC_FLOW_DURATION_SECONDS` | `150` 秒 | 决策前流量聚合窗口。 |
| 预测调度时刻 | `AITC_PREDICTION_HOUR`、`AITC_PREDICTION_MINUTE` | `03:00` | flow/queue 每日预测任务。 |
| 运行数据目录 | `AITC_RUNTIME_DATA_DIR` | `infra/data/runtime` | 长期记忆 JSONL 运行历史。 |
| 运行输出目录 | `AITC_RUNTIME_OUTPUT_DIR` | `logs_data` | 兼容日志、结果与 EXP 输出。 |
| 预测数据目录 | `AITC_PREDICTION_DATA_DIR` | `logs_data` | 预测历史和每日预测文件。 |

## Nacos 配置

当前运行服务通过 `ConfigSyncManager` 启动 floating value、路况、路口结果和时段方案同步任务。时段方案发布脚本仍单独使用 `NACOS_SERVER_URL`、`NACOS_CONSOLE_URL`、`NACOS_USERNAME`、`NACOS_PASSWORD`、`NACOS_NAMESPACE`、`NACOS_GROUP`、`NACOS_TIMEOUT`。本阶段不修改这些旧同步协议，后续再将其收敛到基础设施配置适配层。

## 运行模式

| 模式 | `AITC_RUN_MODE` | 网络绑定 | 配置同步与预测调度 |
| --- | --- | --- | --- |
| 本地回放 | `replay` | `127.0.0.1` | 默认关闭，避免回放触发外部同步和每日预测任务。 |
| 开发服务 | `development` 或未设置 | `127.0.0.1` | 默认开启，保持当前行为。 |
| 生产服务 | `production` | `0.0.0.0` | 默认开启。 |

可通过 `AITC_ENABLE_CONFIG_SYNC` 和 `AITC_ENABLE_PREDICTION_SCHEDULER` 显式覆盖对应模式的后台任务策略。

## 约束

- 未设置环境变量时必须保持现有端口、路径和调度时刻。
- 本地运行产物目录仍由 `.gitignore` 排除。
- 实时协议的行为不由本配置基线改变。
