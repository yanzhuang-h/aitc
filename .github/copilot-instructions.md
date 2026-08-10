# AITC 项目开发规范（Copilot 项目指令）

> 本文件由 Copilot 自动加载。它从 Codex 时代的项目约定迁移而来，开发时请严格遵守。

## 项目背景
AITC 交通信号控制系统，正在进行企业级重构：**Qwen 大模型底座 + 数据仓库底座**的松散耦合架构。数据底座已基本成型，Qwen Agent 编排正在接入。

## 硬性规则
1. **`lib/` 目录禁止修改**：这是受保护的遗留算法层，只能被调用，不能改内部实现。
2. **每步改动完成后主动 Git commit，提交信息使用中文**，用户可直接 `git push`。
3. **注释、文档、提交信息一律使用中文**。
4. **不动算法核心**：重构只移动调用边界，保持旧接口、报文格式和行为兼容。
5. **减法优先**：只做"能合并才合并"的精简，用户明确要求时才抽象新层，避免过度架构化。
6. **协作方代码更新不实时**：除非用户明确授权，避免大范围改动共享文件（如 `Server_AITC.py`、`lib/`）。

## 架构地图
```text
Server_AITC.py        纯启动入口（日志/信号/application.run()）
runtime/              运行编排：application / tcp_server / http_server / decision_pipeline / prediction_*
infra/data/           数据底座：memory/(短/长/查询) + 接收/分类/契约/质量/仓库/聚合/输出/配置/同步
agent/                QwenAgent（符号路由 + Qwen 编排）、DataQueryTools
app/                  配置(config.py) + 核心模型(core/models) + 工具(core/tools) + LLM 客户端(infrastructure/llm)
web/index.html        单文件前端页面
lib/                  受保护算法层（DQN 等，禁止修改）
test/                 自动化测试 + 手工回放客户端
```

## 关键约定
- 模型接入走 **OpenAI-compatible 客户端**（vLLM/SGLang 服务），不直接加载本地 torch/transformers 跑正式推理。
- Qwen 负责编排，DQN 负责算法：Qwen 选工具 -> 工具从数据仓库取上下文 -> 调用算法 -> 汇总答案。
- 结果仓库 + 纯发送器；仓库可替换为 Redis/数据库。
- 长期记忆 = 运行历史 + 经验池 + 配置池（必须持久化的一等能力）。
- 运行数据仓库写入 `infra/data/runtime/runtime/*.jsonl`（已 gitignore），模型权重不提交。
- 日志统一使用 `logging` 分级，禁止裸 `print` 刷屏。

## 常用命令
```powershell
# Windows（aitc conda 环境）
C:\Users\Finn\.conda\envs\aitc\python.exe -m compileall -q infra data runtime agent app
C:\Users\Finn\.conda\envs\aitc\python.exe -m unittest discover -s test -p "test_*.py" -v

# Linux 服务器（llm 环境）
python -m unittest discover -s test -p "test_*.py"
```

## 工作方式
- 动手前先读相关代码和 `todo-done/` 下的开发文档（8-5.md checklist、data-flow-baseline.md、data-contract.md、architecture-migration-plan.md）。
- 大改动先给方案/顺序，用户确认后再实施。
- 每一步完成：验证（编译 + 测试）-> 更新 `todo-done/` 与项目记忆 -> 中文 commit。
