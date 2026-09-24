# AITC 项目开发规范（Copilot 项目指令）

> 本文件由 Copilot 自动加载。它从 Codex 时代的项目约定迁移而来，开发时请严格遵守。

## 项目背景
AITC 交通信号控制系统，正在进行企业级重构：**Qwen 大模型底座 + 数据仓库底座**的松散耦合架构。数据底座已基本成型，Qwen Agent 编排正在接入。

开发环境（2026-09-24 起）：WSL2（Ubuntu），仓库 `~/projects/aitc`，虚拟环境 `.venv`，详见 `todo-done/wsl-migration.md`。

## 硬性规则
1. **`lib/` 目录禁止修改**：这是受保护的遗留算法层，只能被调用，不能改内部实现。
2. **一切改动走「短分支 + PR」**：`main` 已启用保护，禁止直接 push；每个改动从最新 `main` 开短分支（`feature/`、`fix/`、`docs/`、`chore/`），本地验证后推送、提 PR，以 **Squash** 方式合入并删除源分支。
3. **注释、文档、提交信息一律使用中文**；提交信息使用约定式前缀（`feat:` / `fix:` / `docs:` / `chore:`）+ 中文简述。
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
```bash
# WSL 开发环境（仓库根目录下执行，.venv）
.venv/bin/python -m compileall -q infra runtime agent app
.venv/bin/python -m unittest discover -s test -p "test_*.py" -v

# Linux 服务器（llm 环境）
python -m unittest discover -s test -p "test_*.py"

# 分支与 PR（gh CLI）
git switch main; git pull; git switch -c feature/xxx
git push -u origin feature/xxx
gh pr create --fill; gh pr checks; gh pr merge --squash --delete-branch
```

## 工作方式
- 动手前先读相关代码和 `todo-done/` 下的开发文档（8-5.md checklist、data-flow-baseline.md、data-contract.md、architecture-migration-plan.md）。
- 大改动先给方案/顺序，用户确认后再实施。
- 每一步完成（DoD）：本地验证（编译 + 测试）-> 更新 `todo-done/` 与项目记忆 -> 在短分支上中文提交 -> 推送并开 PR（Squash 合入、删除源分支）。
- 分支 / PR / 提交信息的完整规范见 `docs/CONTRIBUTING.md`。

## 反过度工程（最小改动模式）

> 规则来源：[`DietrichGebert/ponytail`](https://github.com/DietrichGebert/ponytail)（MIT）的
> 「lazy senior dev」规则集，此处为中文节选；完整版见 `.github/skills/ponytail*/SKILL.md`。

写任何代码前，停在第一个成立的台阶上（YAGNI 阶梯）：

1. 这件事需要做吗？（YAGNI，先反问「真的需要 X，还是 Y 就够」）
2. 仓库里已经有现成的吗？复用已有 helper / 工具 / 模式，不要重写。
3. 标准库能做吗？
4. 平台原生能力覆盖了吗？
5. 已安装的依赖能解决吗？
6. 能不能一行？
7. 以上都不行，才写最小可用实现。

硬性约束：

- 不加没有被明确要求的抽象；能不加依赖就不加；不写没人要的样板。
- 删除优于新增，朴素优于聪明，文件越少越好。
- 最短可用 diff 优先——但前提是**先真正理解问题**：读任务、读它碰到的代码、把真实流程走通，
  再看哪个台阶能用。改错地方的最小改动不是偷懒，是第二个 bug。
- 修缺陷修根因：grep 所有调用方，在共享函数上修一次，不为每个调用方各打一个补丁。
- 有意砍掉的角（全局锁、O(n²)、朴素启发式）要留 `ponytail:` 注释写明上限与升级路径。
- 非平凡逻辑要留**一个**可运行的检查（assert 自检或最小测试）；一行的小改不需要。

不该省的：理解问题、信任边界的输入校验、防数据丢失的错误处理、安全、明确要求的东西，
以及真实硬件需要的那点校准。

优先用这两个技能：`ponytail`（动手前）、`ponytail-review` / `ponytail-audit`（查过度工程）。
