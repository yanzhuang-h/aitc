# Qwen3 模型服务

AITC 正式运行不直接依赖本地 `torch` 和 `transformers` 加载模型，而是通过 OpenAI-compatible API 调用独立的 Qwen3 服务。

## 推荐部署方式

优先使用 Linux、WSL2 或独立 GPU 服务器运行 vLLM/SGLang。Windows 原生环境通常不适合作为 vLLM/SGLang 的正式运行环境，尤其是新型号显卡需要匹配较新的 CUDA、PyTorch 和驱动版本。

模型目录约定为：

```text
infra/model/qwen/Qwen3-0.6B/
```

模型权重已被 `.gitignore` 排除，不提交到 Git 仓库。

## vLLM

在模型服务所在环境安装并启动：

```bash
pip install "vllm>=0.8.5"
vllm serve /path/to/Qwen3-0.6B \
  --served-model-name Qwen3-0.6B \
  --host 0.0.0.0 \
  --port 8000 \
  --enable-reasoning \
  --reasoning-parser deepseek_r1
```

## SGLang

也可以使用 SGLang：

```bash
pip install "sglang>=0.4.6.post1"
python -m sglang.launch_server \
  --model-path /path/to/Qwen3-0.6B \
  --host 0.0.0.0 \
  --port 8000 \
  --reasoning-parser qwen3
```

## 验证服务

先确认服务能够返回模型列表：

```bash
curl http://127.0.0.1:8000/v1/models
```

再在 AITC 的 `aitc` 环境中配置客户端：

```powershell
$env:AITC_LLM_BASE_URL = "http://127.0.0.1:8000/v1"
$env:AITC_LLM_MODEL = "Qwen3-0.6B"
$env:AITC_LLM_API_KEY = "EMPTY"
$env:AITC_LLM_ENABLE_THINKING = "false"
```

客户端入口是：

```python
from app.infrastructure.llm import OpenAICompatibleLLMClient

client = OpenAICompatibleLLMClient(
    base_url="http://127.0.0.1:8000/v1",
    model="Qwen3-0.6B",
)
result = client.chat([
    {"role": "user", "content": "请简要说明交通流量和排队长度的关系。"},
])
print(result.content)
```

## 当前边界

`infra/model/qwen/main.py` 仍然保留为本地 `transformers` smoke test，用来诊断模型文件和本地依赖。正式 Agent 链路使用 `app.infrastructure.llm.OpenAICompatibleLLMClient`，因此 AITC 进程不需要直接加载模型权重。
