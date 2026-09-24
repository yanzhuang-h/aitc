# WSL 开发环境迁移说明（2026-09-24）

## 1. 背景

原开发环境为 Windows 原生 + conda `aitc` 环境。为统一 Linux 工具链、
与服务器部署环境及 GitHub Actions CI（ubuntu-latest）对齐，开发环境整体
迁入 WSL2（Ubuntu）。

## 2. 迁移结果

| 项 | 迁移前（Windows） | 迁移后（WSL2） |
| --- | --- | --- |
| 仓库目录 | `C:\Users\Finn\Desktop\dkrg-aitc\AITC` | `~/projects/aitc` |
| Python | conda 环境 `aitc` | 仓库内 `.venv`（Python 3.11.16，已 gitignore） |
| Git / PR | Git for Windows | SSH key + `gh` CLI（账号 `yanzhuang-h`） |

依赖清单统一维护在 `requirements.txt`（本地与 CI 共用单一来源），Python 版本记录在 `.python-version`：

```bash
cd ~/projects/aitc
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip -r requirements.txt
```

`.env`（LLM 配置）与运行数据均在 gitignore 范围内，保留在本地，不随迁移提交。

## 3. 常用命令（WSL 终端）

```bash
cd ~/projects/aitc
.venv/bin/python -m compileall -q infra runtime agent app
.venv/bin/python -m unittest discover -s test -p "test_*.py"
```

## 4. 验证结果

- 编译检查（compileall）：通过
- 单元测试：`Ran 136 tests ... OK`
- 关键依赖：`mcp 1.30.0` / `APScheduler 3.11.3` / `chinesecalendar 1.11.0` / `numpy 2.4.6`

## 5. 约定变更

- 本地验证命令统一改为 WSL `.venv/bin/python`，已同步更新
  `.github/copilot-instructions.md`、`docs/CONTRIBUTING.md`、
  `agent/mcp_server.py` 与 `infra/model/qwen/README.md` 中的示例；
- 依赖清单以 `requirements.txt` 为单一来源（本地 `.venv` 与 CI 共用），
  Python 版本统一记录在 `.python-version`；
- Windows 原目录不再作为开发环境；
- 服务器部署目录与运行配置保持不变。
