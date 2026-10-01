# Day 5 学习笔记：配置体系收口 + 遗留盘点

> 目标：把「配置抽象」这条主线一次做完，并给根目录遗留模块定性。

## 一、本轮落地（PR #34 / #35）

1. **配置路径收敛（候选 #4）**：新增 `app/paths.py` 唯一路径来源 + 环境变量覆盖（`AITC_GREEN_WAVE_CORRIDORS_PATH` / `AITC_INTERSECTION_RESULT_CONFIG_PATH` / `AITC_ROAD_INFO_PATH`）；`phase_check.py`、`green_wave_api_adapter.py`、`time_schedule/get_sch_for_cross.py` 三处改为引用。
2. **候选 #2 已确认完成**：`RuntimeSettings` 字段默认值即唯一来源，`from_environment` 统一 `cls.<字段>` 回退（无重复）。
3. **候选 #3 结论**：生产路径已全部显式注入 settings；三处 `logs_data` 默认仅服务单测/独立脚本 → 保留占位默认 + 注释注明注入点。
4. **遗留文件清理（候选 #6/#7 部分）**：删除 `intersection_to_rid_lambda.py`（1128 行）、`new_online_data_map_lambda.py`（714 行，二者为 `gen_online_config.py` 生成产物、无导入方）、`magic_hand.py`（零引用）。净删 1848 行。

## 二、遗留定性结论

| 文件 | 定性 | 处置 |
| --- | --- | --- |
| `config_check.py` / `gen_online_config.py` / `gen_api_docs.py` | 离线工具（`from Lambdas import *`） | 移 `tools/` 待做（需 sys.path 修正） |
| 根 `time_schedule.py`（688，Flask） | 被 `time_schedule/` 包遮蔽，无导入方 | 移 `legacy/`（C4，中风险待确认） |
| `path_config.py`（62） | 被 `time_schedule/get_time_tools.py` 使用 | 与 C4 一起处理 |

## 三、待办（部署检查）

- `AITC_RUN_MODE=production` 启动冒烟：绑定 0.0.0.0、端口 65432/8088、`/health`、回放冒烟、日志轮转路径（不重做部署）。
