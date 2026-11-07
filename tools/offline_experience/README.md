# 离线经验表工具（骨架）

把离线学习收敛成**一条命令**：训练 → 补气 → 校验 → （可选）发布，产物是带版本与清单的经验表。

> 当前状态：**骨架**。只实现参数解析、输入检查与 `--dry-run`；训练/补气/发布由离线学习负责人补齐。
> 契约以此文件为准，实现不得改变参数名、产物路径与退出码语义。

## 用法

```bash
python tools/offline_experience/cli.py \
  --dates 2026-09-01,2026-09-02 \
  --roads 1700542,1700545 \
  --dry-run
```

## 参数契约

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `--dates` | 是 | — | 训练源日期，逗号分隔 `YYYY-MM-DD`，可给多天 |
| `--roads` | 是 | — | 训练路口 ID，逗号分隔 |
| `--flow-dir` | 否 | `logs_data/flow` | 流量日志目录（`<date>_flow.txt`） |
| `--extend-dir` | 否 | `logs_data/extend` | 阶段日志目录（`<date>_extend.txt`） |
| `--cross-info` | 否 | `lib/cross_info.json` | 路口渠化/相位配置 |
| `--output` | 否 | `logs_data/training_results/offline_candidate.json` | 候选经验表输出 |
| `--report` | 否 | `<output>.report.json` | 运行报告 |
| `--no-fill` | 否 | 开启补气 | 跳过补气（buqi）步骤 |
| `--runtime-table` | 否 | `lib/offline_experience.json` | 发布目标（`--activate` 时生效） |
| `--versions-dir` | 否 | `lib/experience_versions` | 版本目录 |
| `--manifest` | 否 | `<versions-dir>/active_manifest.json` | 激活清单 |
| `--dry-run` | 否 | 关 | 只解析输入并输出计划，不写任何文件 |
| `--activate` | 否 | 关 | 校验通过后发布到 `--runtime-table`，写版本与清单 |

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功（`--dry-run` 时为输入检查通过） |
| 1 | 运行期错误（训练/补气/发布异常） |
| 2 | 参数错误（缺参、格式非法） |
| 3 | 输入不完整（缺日志/缺 cross_info 配置） |

## 产物

- 候选表：`--output`，格式与 `lib/offline_experience.json` 完全一致
  （`路口 → 方向 → 绿灯时长 → 10 个车道的容量向量`）
- 报告：`--report`，至少包含 `status`、`dates`、`roads`、`missing_inputs`、
  `row_count`、`changed_roads`、`validation`
- 发布（`--activate`）：`--runtime-table` + `--versions-dir/experience_<UTC时间>_<hash12>.json`
  + `_previous.json` + `active_manifest.json`

## 现有逻辑映射（实现时直接复用，不要重写算法）

| 步骤 | 现有实现 |
|---|---|
| 训练 | `lib/data_ANS/E_T_new.py::run_training()`（`AITC_TRAIN_DATES`、`AITC_TRAIN_ROAD_IDS`、`AITC_EXPERIENCE_OUTPUT`） |
| 补气 | `lib/data_ANS/buqi_new2.0.py`（`AITC_BUQI_INPUT/OUTPUT/REPORT/ROADS`） |
| 表校验 | `lib/data_ANS/experience_release.py::validate_experience_table()` |
| 发布 | `lib/data_ANS/experience_release.py::release_bootstrap_experience_table(..., activate=True)` |

## 迁移清单（负责人执行）

搬进本目录（离线专用）：
- `E_T_new.py`、`buqi_new2.0.py`、`data_chou.py`、`lan_jingyan.py`、`compare_experience_tables.py`
- 对应测试（`test_e_t_cycle_gate.py` 等）

留在 `lib/data_ANS/`（离线+在线共用，不能动）：
- `cycle_quality.py`、`lane_policy.py`、`raw_data_cleaning.py`、`experience_candidate_audit.py`

留在原地（在线链路）：
- `experience_runtime.py`、`experience_pool.py`、`experience_release.py`、
  `flow_time_allocator.py`、`flow_allocator_shadow.py`

搬迁时删除 `try: from lib... except ModuleNotFoundError: from ...` 这类 sys.path 兼容代码，
改为包内导入或统一从仓库根导入。

## 验收标准

1. `--dry-run` 在缺日志时返回 3，并列出缺失文件。
2. 同一天日志下，新工具产物与旧脚本产物逐 key 比对一致（允许顺序差异），由 parity 测试固化。
3. `--activate` 后 `active_manifest.json` 有新的 `release_id` 与 `active_sha256`，回滚可用。
4. 运行时不引用本目录任何模块（`grep` 校验），搬迁不影响服务。

## 测试

```bash
.venv/bin/python -m unittest test.test_offline_experience_cli -v
```
