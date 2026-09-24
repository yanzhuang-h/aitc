# aitc-main 合并说明（2026-09-24）

## 1. 背景

`AITC_V2.62.1`（与 GitHub main 同步的工作副本）与服务器部署线 `aitc-main`
长期并行开发、各自产生迭代。本次以部署线（已在服务器正常运行）为基准对
两条线做三方合并，产出单一代码库：

- 本地目录 `AITC_V2.62.1` 已更名为 `AITC`；
- `aitc-main` 目录已删除，其全部有效内容已合入本仓库；
- 后续开发统一在 `AITC` 进行，并推送 GitHub main。

## 2. 合并方法

- 共同祖先：`42a6968`（2026-08-11）。
- 部署线快照提交：`336db71`（以 `42a6968` 为父提交，导入 `aitc-main` 全量内容）。
- 三方合并提交：`8c83126`（`fb502e6` 与 `336db71` 合并）。

冲突解决（4 处）：

| 文件 | 解决方式 |
| --- | --- |
| `runtime/application.py` | 保留 `control_processor` 复用（GitHub 侧重构），同时接入 V65 控制快照参数 |
| `lib/data_ANS/experience_runtime.py` | V2.65 路口清单基础上叠加部署线新增 7 个试点路口 |
| `lib/data_ANS/flow_allocator_shadow.py` | 同上，叠加 7 个新路口 |
| `lib/experience_pool/new_wwx.json` | 采用部署线版本（数据更新更全） |

新增试点路口：`1700448 / 1700449 / 1700450 / 1700542 / 1700545 / 2272 / 2620`。

## 3. 合并后保留的能力

部署线（V65 及 2026-09-11 前迭代）：

- 经验池调度默认启用（`AITC_EXPERIENCE_POOL_ENABLED`）；
- Nacos 同步默认关闭（`AITC_ENABLE_CONFIG_SYNC`）；
- 控制快照能力（`AITC_CONTROL_SNAPSHOT_ENABLED`，默认关闭）；
- 固定决策周期语义、`lib/Global_intersection_coordinate.py` 缺失 datetime 修复；
- 新试点路口调度与经验池数据。

GitHub 线：

- AgentHarness 统一入口与三层路由（`/api/agent/query`、`/api/agent/tools`、`/api/agent/calls`）；
- MCP 服务器（`agent/mcp_server.py`）与控制函数工具集（`app/core/tools/control_function_tools.py`）；
- 绿波服务、接口测试页等既有能力。

## 4. 未入库文件说明

- 部署线 `lib.zip`、`infra/data/runtime/runtime/tmp*` 视为构建/临时产物，未入库；
- 部署线运行数据 `infra/data/runtime/runtime/{extend,flow,online}.jsonl` 已同步到本地，
  原有本地版本备份为 `*.jsonl.local.bak`（两者均在 gitignore 范围内）。

## 5. 验证结果

```text
compileall：通过
python -m unittest discover -s test -p "test_*.py"
Ran 136 tests ... OK
```

## 6. 后续约定

- 开发目录：WSL2（Ubuntu）`~/projects/aitc`（`.venv`），见 `todo-done/wsl-migration.md`；
- 推送：`git push`（origin = git@github.com:yanzhuang-h/aitc.git）；
- 服务器部署目录 `/home/feile/aitc2.0/aitc-main` 保持现状，待下次部署时同步本仓库。
