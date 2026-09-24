# 开发协作流程（分支 + PR）

> 2026-09-24 起启用。目标：`main` 始终稳定可运行，所有改动走「短分支 + PR」合入。
> 流程对齐主流团队（含实习团队）的协作方式，命令可平移使用。

## 一、分支模型（简化主干式）

| 分支 | 用途 | 生命周期 |
| --- | --- | --- |
| `main` | 稳定主线，任何时候可运行 | 常驻，受保护 |
| `feature/<名称>` | 新功能 | 1~3 天，合入即删 |
| `fix/<名称>` | 缺陷修复 | 尽量短 |
| `docs/<名称>`、`chore/<名称>` | 文档、配置、依赖等杂务 | 尽量短 |

- 分支名用简短英文小写 + 连字符，如 `feature/experience-pool-scheduler`
- 一个分支只做一件事，不混入无关改动

## 二、一次改动的完整流程

### 1. 同步并开分支

```powershell
git switch main
git pull
git switch -c feature/xxx
```

### 2. 小步开发与提交

提交信息 = 约定式前缀 + 中文简述（见第三节）。

### 3. 本地验证（全过再推送）

```powershell
# Windows（aitc conda 环境）
C:\Users\Finn\.conda\envs\aitc\python.exe -m compileall -q infra runtime agent app
C:\Users\Finn\.conda\envs\aitc\python.exe -m unittest discover -s test -p "test_*.py"

# Linux 服务器（llm 环境）
python -m unittest discover -s test -p "test_*.py"
```

### 4. 推送并创建 PR

```powershell
git push -u origin feature/xxx
gh pr create --fill    # 或网页操作；描述自动套用 .github/pull_request_template.md
```

> 首次使用 gh：先执行 `gh auth login --git-protocol ssh --web`，按提示在浏览器完成授权。

### 5. 自审并合入

在 PR 的 Files changed 中过一遍 diff -> **Squash merge** -> 自动删除源分支。

### 6. 回到 main 并清理

```powershell
git switch main
git pull
git fetch --prune
```

## 三、提交信息规范

| 前缀 | 含义 | 示例 |
| --- | --- | --- |
| `feat:` | 新功能 | `feat: 新增经验池调度工具` |
| `fix:` | 缺陷修复 | `fix: 修复绿波服务顺序问题` |
| `docs:` | 文档 | `docs: 补充数据契约说明` |
| `chore:` | 配置、杂务、依赖 | `chore: 启用分支保护` |

描述用中文，一句话说清“做了什么”；需要时在正文补充“为什么”。

## 四、PR 规范

- 标题与提交信息同格式（`feat: ...`）
- 描述自动套用 `.github/pull_request_template.md`（背景 / 改动 / 验证 / 自查 / 影响面）
- 合并方式统一 **Squash**（仓库配置为仅允许 Squash），合入后自动删除源分支
- 每个 PR 自动运行 CI（编译 + 单元测试），**通过后才能合入**
- 单人阶段无需批准即可合入；引入评审后可在仓库设置中要求批准数

## 五、CI（自动检查）

`.github/workflows/ci.yml` 在每次 PR 与 main 推送时自动运行：

1. 编译检查：`python -m compileall -q infra runtime agent app`
2. 单元测试：`python -m unittest discover -s test -p "test_*.py"`

查看方式（PR 页面会自动显示检查状态）：

```powershell
gh pr checks               # 当前 PR 的检查结果
gh run list -L 10          # 最近的工作流运行
gh run view --log-failed   # 失败时查看日志
```

## 六、main 分支保护（已启用）

- 必须通过 PR 合入，禁止直接 push（管理员同样受限）
- 禁止 force push 与删除分支
- 修改入口：GitHub 仓库 Settings -> Branches / Rulesets

## 七、常用命令速查

```powershell
git status -sb                 # 查看分支及领先/落后情况
git switch main; git pull      # 同步主线
git switch -c fix/xxx          # 从当前 HEAD 开修复分支
git log --oneline -10          # 最近提交
gh pr status                   # 我的 PR 状态
gh pr view --web               # 浏览器打开当前 PR
gh pr checks                   # 查看 PR 检查（CI）结果
```
