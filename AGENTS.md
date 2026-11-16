# AITC workspace notes for agents

本仓库位于 WSL：`/home/finn/projects/aitc`；Windows 侧 DSH 通过
`\\wsl.localhost\Ubuntu\home\finn\projects\aitc` 访问（9p 共享）。

本文件会被 DSH / Codex / Claude Code 等读取为工作区指令。

## 0. 适用范围

- **Windows 上的 DSH**：按第 1 节走 WSL 写文件。
- **WSL/Linux 内原生运行的 agent**（Codex CLI、Claude Code 等）：直接按常规读写即可，
  第 1 节的限制与你无关；命令和 git 在 WSL 内执行即可。
- 人用 VS Code Remote/WSL 编辑无需遵守第 1 节。

## 1. 写文件必须走 WSL（仅 Windows DSH）

DSH 的 `write` / `edit` 工具在这个共享上不可用：

- 新建文件 → `ENOTSUP ... link ...`（9p 不支持硬链接）
- 修改文件 → `GetFileSecurityW EIO (Win32 1)`（9p 不支持 Windows 安全描述符）

不要反复重试这两个工具。规则：

- 读取、搜索、列目录：用 DSH 原生 `read` / `grep` / `glob`。
- 写入、修改：先暂存到 Windows，再用 WSL 落到仓库：

  1. 用 `write` 工具写 `C:\Users\Finn\AppData\Local\Temp\dsh-stage\<name>`（内容按最终文件给全）。
  2. 执行：

     ```powershell
     wsl.exe -d Ubuntu -- bash -lc "mkdir -p <dir> && cat /mnt/c/Users/Finn/AppData/Local/Temp/dsh-stage/<name> > /home/finn/projects/aitc/<path> && rm -f /mnt/c/Users/Finn/AppData/Local/Temp/dsh-stage/<name>"
     ```

  `cat >` 新建文件为 0644、LF、属主 finn；覆盖已有文件时保留原 mode。

- 二进制文件不要走 `write` 工具（只支持 UTF-8），用 `pwsh` 的 `Copy-Item` 从已有文件复制。
- 不要用 PowerShell 5.1 的 `Set-Content -Encoding utf8`：会写 BOM，破坏 `.sh` / shebang。

## 2. 命令走 WSL

```powershell
wsl.exe -d Ubuntu --cd /home/finn/projects/aitc -- bash -lc "<command>"
```

- Python：`.venv/bin/python`（3.11.16）
- 测试：`.venv/bin/python -m unittest discover -s test -p 'test_*.py'`
- Windows git 是 `core.autocrlf=true`；`.gitattributes` 已固定 `* text=auto eol=lf`。git 操作优先在 WSL 内执行。

## 3. 背景

Windows DSH 宿主无法用原生文件工具改这个 9p 工作区；`workspace-write` 沙箱也因 ACL 不可用，
本工作区应使用 `danger-full-access`。

## 4. 本地开发与生产协作边界

涉及配时行为、训练或参数的工作，先说明我方可独立完成的内容、
需要生产环境提供的材料或配合，以及两侧分别如何验证。
缺少生产材料时继续推进不依赖它的工作，明确记录尚不能下结论的部分。

- 本地真实历史日志可验证解析、经验积累、计算输出和配置边界；
  不能单独证明当前生产状态、发送成功、信号机实际执行或交通效果改善。
- 生产证据应与问题时段对应：运行版本、配置快照、相关运行参数、
  最终下发与执行记录、学习任务及经验版本记录。按问题列出具体缺项。
- 未确认的现场配置与反馈语义，保留为待核实事项；
  不根据猜测直接改成默认业务规则。
- PR 写清我方验证结果、所需生产配合及现场验收状态；
  合并、打包、部署、现场验收分别记录。文档类改动可注明无需现场验收。

排查、修复和提交 PR 不自动触发打包或发布；仅在用户明确要求时运行发布打包流程。

短时定位优先复用DSH迁移记录、飞书和已有部署流程，不默认要求运维重报已知版本、
重发一致配置或提供整日原始输入。运维说明尽量只含运行时长、一次必要操作和明确的
回传文件；优先通过不改变配时行为的日志补齐信息。确需更多材料时再按证据提出。
