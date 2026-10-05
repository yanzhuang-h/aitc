# AITC：交通信号配时算法系统

AITC 接收视频、雷达等多源交通数据，通过既有经验、时刻表和规则策略生成路口配时，
完成协调、校验和 TCP 下发。V2 正在逐步加入统一数据状态、专家、LangGraph 和可选 Qwen 增强。

当前代码完成 Phase 0–6 的基础组件。**Qwen Planner/Reviewer、完整 Safety Gate 和
逐决策 tracing 尚待 Phase 7–9；基础控制链可以独立于模型服务运行。**

- [当前架构总览与阶段进度](docs/v2_current_architecture.md)
- [原始业务链路审计](docs/v2_baseline_audit.md)
- [核心数据与配时契约](docs/v2_contracts.md)
- [LangGraph 控制流程](docs/v2_langgraph_harness.md)
- [Qwen / Mock / Disabled 模型网关](docs/v2_model_gateway.md)

生产入口为 `Server_AITC.py`，应用装配在 `runtime/application.py`。
依赖由 `requirements.txt` 维护，Python 版本见 `.python-version`。

```bash
# 使用已安装项目依赖的 Python 环境；本仓库本地环境为 .venv
AITC_LLM_ENABLED=false .venv/bin/python Server_AITC.py
```

本项目负责算法系统；本轮 V2 工作不包含前端可视化平台。

```bash
.venv/bin/python -m unittest discover -s test -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/data_ANS/tests -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/control_functions/tests -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/control_functions/global_processors/tests -p 'test_*.py'
```
