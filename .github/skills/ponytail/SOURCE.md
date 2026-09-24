# 出处与许可（ponytail 技能组）

- **来源仓库**：<https://github.com/DietrichGebert/ponytail>
- **许可**：MIT
- **拉取日期**：2026-09-24
- **改写情况**：全部 `SKILL.md` 为原文照搬，未做改写。
- **同仓库规则文件**：随本次安装，`.github/copilot-instructions.md` 末尾新增「反过度工程（最小改动模式）」
  一节，内容为该仓库 `.github/copilot-instructions.md` 的中文节选（原文为英文）。

## 本目录包含

| 目录 | 作用 |
| --- | --- |
| `ponytail/` | 主技能：写/改/重构/评审时强制 YAGNI 阶梯与最小实现，支持 lite / full / ultra 强度 |
| `ponytail-review/` | 只针对过度工程的 diff 评审：该删什么、用什么替代（一行一条） |
| `ponytail-audit/` | 全仓过度工程审计：输出排序后的可删/可简化/可换标准库清单（只报告不改） |
| `ponytail-debt/` | 收集代码中的 `ponytail:` 注释，形成技术债台账 |
| `ponytail-gain/` | 展示 ponytail 的基准收益面板 |
| `ponytail-help/` | 用法速查卡 |

## 未一并安装的上游内容

上游仓库还包含 `hooks/`（Cursor 钩子）、`commands/`（其他 CLI 的斜杠命令）、`benchmarks/`、
`scripts/` 等面向其它客户端的资产，本工作区只需 skill 形态，故未复制。
