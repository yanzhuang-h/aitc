# AITC 架构迁移规划

## 目标

本项目参考企业级 Python Agent/RAG 工程的分层方式逐步演进，但保持 AITC 的实时交通数据接收、周期决策和控制结果发送能力。迁移期间不修改 `lib/` 中的既有算法实现，也不一次性替换现有 TCP/HTTP 协议。

目标结构不是通用文档问答系统，而是以实时交通数据和智能决策为中心的 Agent 项目：

```text
app/
├── main.py                    # 最终统一启动入口
├── config.py                  # 运行配置与环境变量
├── api/                       # 管理 API：健康、查询、配置、Agent
├── core/
│   ├── agent/                 # Agent、工具、意图与未来 Qwen harness
│   ├── memory/                # 长期、短期记忆与统一查询语义
│   ├── decision/              # 决策编排与控制结果模型
│   └── models/                # 跨模块数据契约和枚举
├── infrastructure/
│   ├── data/                  # JSONL、Redis、数据库等存储实现
│   ├── messaging/             # TCP、HTTP 接入与结果发送适配
│   ├── config/                # 配置文件与 Nacos 同步适配
│   └── observability/         # 日志、质量监控和追踪
├── etl/                       # 回放、清洗、训练与离线数据流水线
└── runtime/                   # 迁移期间保留的运行编排
```

## 当前架构映射

| 当前模块 | 当前职责 | 目标归属 | 处理策略 |
| --- | --- | --- | --- |
| `Server_AITC.py` | 启动、日志、信号处理 | `app/main.py` | 最后迁移，保持现有启动方式可用。 |
| `runtime/` | TCP/HTTP 服务、决策、调度、生命周期 | `runtime/` -> `core/decision` 与 `infrastructure/messaging` | 先维持运行边界，再按职责逐步迁移。 |
| `agent/` | 符号 Agent、查询工具、Qwen 入口 | `app/core/agent/` | 当前先整理工具协议和符号流程，暂不接入 Qwen。 |
| `infra/data/memory/` | 短期记忆、长期记忆、统一查询 | `app/core/memory/` | 作为核心语义保留；后续只替换底层实现。 |
| `infra/data/repository.py`、`storage.py` | JSON/JSONL 存储实现 | `app/infrastructure/data/` | 后续通过存储端口支持 Redis、数据库。 |
| `infra/data/receiver.py`、`ingest.py` | 接收后分类、持久化、缓存 | `app/infrastructure/messaging/` | 保留现有协议行为，逐步明确适配器边界。 |
| `infra/data/config*.py` | 配置读取与 Nacos 同步 | `app/infrastructure/config/` | 先统一配置模型，再迁移适配。 |
| `infra/data/quality.py`、`writer.py`、`output_store.py` | 数据质量、日志和兼容输出 | `app/infrastructure/observability/` | 保留输出格式，后续独立可观测性。 |
| `infra/data/contracts.py`、`schemas.py`、`classifier.py` | 数据契约、模型、分类 | `app/core/models/` | 先稳定契约，再进行目录迁移。 |
| `test/` | 单测、回放客户端、集成测试 | `test/` | 保留单一测试目录，迁移时同步调整导入。 |
| `lib/` | 既有算法实现 | 遗留算法边界 | 禁止修改；仅从决策编排层调用。 |
| 根目录预测与业务模块 | 既有算法与业务逻辑 | 待分类 | 先区分算法实现和运行编排，不直接移动。 |

## 分阶段 Checklist

### 第一阶段：架构边界与配置基线

- [x] 将长短期记忆及查询层收敛到 `infra/data/memory/`。
- [x] 移除已无调用方的旧记忆兼容入口。
- [x] 记录当前架构到目标架构的映射与迁移约束。
- [x] 盘点端口、路径、周期、Nacos 等配置来源，定义统一配置清单。
- [x] 新增不改变现有启动方式的配置加载入口。
- [x] 定义运行模式：本地回放、开发服务、生产服务。

### 第二阶段：核心模型与基础设施边界

- [x] 收敛 Agent 工具响应与决策结果模型，并保持既有控制报文兼容。
- [ ] 明确短期记忆、长期记忆与存储端口的接口边界。
- [ ] 将 JSONL、结果文件、预测历史等具体实现标记为基础设施适配器。
- [ ] 保持现有数据契约与回放测试作为迁移回归基线。

### 第三阶段：Agent Harness

- [ ] 将符号 Agent 与数据查询工具整理为独立 Agent 核心。
- [ ] 规范工具输入、输出、错误和权限契约。
- [ ] 在回放和工具测试稳定后接入 Qwen 模型适配器。
- [ ] 为模型调用、工具调用与决策结果补充可观测性。

### 第四阶段：管理 API 与部署

- [ ] 引入 FastAPI 管理 API，不替换实时 TCP/HTTP 数据协议。
- [ ] 先提供 health、运行数据查询、历史数据查询、配置查询和 Agent 调用。
- [ ] 引入 `pyproject.toml`、`.env.example` 和依赖分组。
- [ ] 在启动与配置边界稳定后再补 Dockerfile、docker-compose 和部署文档。

## 下一步

下一项开发任务是整理跨模块数据模型，优先盘点运行记录、决策结果和 Agent 工具响应，确定哪些可以稳定为核心模型。
