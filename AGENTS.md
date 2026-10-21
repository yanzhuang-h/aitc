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
