# 出处与许可（code-simplifier）

- **来源仓库**：<https://github.com/getsentry/skills>（Apache-2.0）
- **原始路径**：`skills/code-simplifier/SKILL.md`
- **拉取日期**：2026-09-24
- **上游原本出处**：Anthropic 官方插件
  <https://github.com/anthropics/claude-plugins-official/blob/main/plugins/code-simplifier/agents/code-simplifier.md>
- **改写情况**：`SKILL.md` 为原文照搬，未做改写。

## 与 AITC 的差异（待定，未改）

`SKILL.md` 第 2 节「Apply Project Standards」引用的是 Sentry 前端的 `CLAUDE.md` 约定
（ES 模块、箭头函数、React Props 类型等），与 AITC 的 Python 项目不符。
如需对齐，可把该节换成 AITC 的既有约定（`lib/` 只包装不改算法、中文注释与提交、
`compileall` + `unittest` 验证等）——另行提交，保持本节内容的可追溯性。
