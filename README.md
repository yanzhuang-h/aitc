# AITC：交通信号配时算法系统

AITC 接收视频、雷达等交通数据，通过经验、时刻表和规则生成路口配时。周期任务使用固定控制策略生成候选，
在全局协调后通过确定性安全校验，再写入结果仓库并由 TCP 服务发送。每轮日志记录输入、候选、最终方案和安全校验。

HTTP Agent 与 MCP 工具服务各有入口。HTTP Agent 可以使用 Qwen 或 DeepSeek，周期配时直接调用固定策略。
AgentScope 2.0.12 和 MCP SDK 2.3.0 由 requirements.txt 统一维护，供 MCP 工具和后续原生 Agent 开发使用。

- [原始业务链路审计](docs/v2_baseline_audit.md)
- [核心数据与配时契约](docs/v2_contracts.md)
- [Qwen / DeepSeek / Mock / Disabled 模型网关](docs/v2_model_gateway.md)
- [确定性 Safety Gate](docs/v2_safety_gate.md)
- [逐决策追踪](docs/v2_decision_tracing.md)
- [Phase 0–10 架构与验收记录](docs/v2_current_architecture.md)

生产入口为 `Server_AITC.py`，应用装配在 `runtime/application.py`。
依赖由 `requirements.txt` 维护，Python 版本见 `.python-version`。

```bash
# 使用已安装项目依赖的 Python 环境；本仓库本地环境为 .venv
AITC_LLM_ENABLED=false .venv/bin/python Server_AITC.py
```

为 HTTP Agent 启用 DeepSeek 时，在 `.env` 中设置下列字段：

```dotenv
AITC_LLM_ENABLED=true
AITC_MODEL_PROVIDER=deepseek
AITC_MODEL_NAME=deepseek-flash
AITC_MODEL_BASE_URL=https://api.deepseek.com
AITC_MODEL_API_KEY=你的密钥
AITC_LLM_ENABLE_THINKING=false
```

然后启动服务：

```bash
.venv/bin/python Server_AITC.py
```

MCP 工具服务通过 stdio 提供工具列表与调用。

```bash
.venv/bin/python -m agents.mcp_server
```

```bash
.venv/bin/python -m compileall -q app datahub control agents models safety runtime infra test
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s test -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/data_ANS/tests -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/control_functions/tests -p 'test_*.py'
.venv/bin/python -m unittest discover -s lib/control_functions/global_processors/tests -p 'test_*.py'
```
