# AITC：交通信号配时算法系统

AITC 接收视频、雷达等多源交通数据，通过既有经验、时刻表和规则策略生成路口配时，
完成协调、确定性安全校验和 TCP 下发。V2 已加入统一数据状态、专家、LangGraph 和可选模型增强。

当前代码完成 Phase 0–8：基础控制链、统一模型网关、受约束 Planner/Reviewer 和 Safety Gate。
周期模型增强默认关闭，启用后在视频证据不足时查询工具、审查原算法候选。
最终方案在全局协调后经过不依赖模型的安全门；逐决策 tracing 留待 Phase 9。

- [当前架构总览与阶段进度](docs/v2_current_architecture.md)
- [原始业务链路审计](docs/v2_baseline_audit.md)
- [核心数据与配时契约](docs/v2_contracts.md)
- [LangGraph 控制流程](docs/v2_langgraph_harness.md)
- [Qwen / DeepSeek / Mock / Disabled 模型网关](docs/v2_model_gateway.md)
- [受约束的 Qwen Planner / Reviewer](docs/v2_qwen_agent.md)
- [确定性 Safety Gate](docs/v2_safety_gate.md)

生产入口为 `Server_AITC.py`，应用装配在 `runtime/application.py`。
依赖由 `requirements.txt` 维护，Python 版本见 `.python-version`。

```bash
# 使用已安装项目依赖的 Python 环境；本仓库本地环境为 .venv
AITC_LLM_ENABLED=false .venv/bin/python Server_AITC.py

# 显式开启周期 Qwen 规划与审查
AITC_LLM_ENABLED=true AITC_MODEL_PROVIDER=qwen \
AITC_CONTROL_AGENT_ENABLED=true .venv/bin/python Server_AITC.py

# 在已被 Git 忽略的 .env 中配置 DeepSeek，避免密钥进入命令历史
AITC_LLM_ENABLED=true
AITC_MODEL_PROVIDER=deepseek
AITC_MODEL_NAME=deepseek-flash
AITC_MODEL_BASE_URL=https://api.deepseek.com
AITC_MODEL_API_KEY=你的密钥
AITC_LLM_ENABLE_THINKING=false
AITC_CONTROL_AGENT_ENABLED=true

.venv/bin/python Server_AITC.py
```

本项目负责算法系统；本轮 V2 工作不包含前端可视化平台。

```bash
.venv/bin/python -m unittest discover -s test -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/data_ANS/tests -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/control_functions/tests -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/control_functions/global_processors/tests -p 'test_*.py'
```
