# 出处与许可（code-simplifier）

- **来源仓库**：<https://github.com/getsentry/skills>（Apache-2.0）
- **原始路径**：`skills/code-simplifier/SKILL.md`
- **拉取日期**：2026-09-24
- **上游原本出处**：Anthropic 官方插件
  <https://github.com/anthropics/claude-plugins-official/blob/main/plugins/code-simplifier/agents/code-simplifier.md>
- **改写情况**：`SKILL.md` 为原文照搬，未做改写。

## 与上游的差异（已本地化 1 处）

`SKILL.md` 正文与上游一致，唯一改动是第 2 节「Apply Project Standards」：
上游引用 Sentry 前端的 `CLAUDE.md` 约定（ES 模块、箭头函数、React Props 类型等），
本仓库已替换为 AITC 的项目约定（Python 3.11 风格、中文注释与提交、不新增依赖、
`lib/` 保持行为兼容、`compileall` + `unittest` 验证）。

其余章节如需与上游同步（例如上游新增规则），直接对照上游路径覆盖后重做本节调整即可。
