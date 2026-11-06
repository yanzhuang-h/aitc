# legacy：已退役的旧代码

这里的模块不参与生产运行链、测试套件和 CI 编译目标，只保留作参考。
运行链的路径职责已由 `app/paths.py` 接管，时间表读取由 `time_schedule/` 包负责。

| 文件 | 原位置 | 退役原因 |
|---|---|---|
| `time_schedule.py` | 仓库根目录 | 旧 Flask 时间表服务。根目录同名 `time_schedule/` 包长期把它遮蔽（`import time_schedule` 解析到包），依赖的 `flask` 也不在 `requirements.txt` 中 |
| `path_config.py` | 仓库根目录 | 旧路径配置（`logs_data/*` 目录表，导入时调用 `create_directories()`）。运行链改用 `RuntimeSettings` 与 `app/paths.py` |

迁移时同步做了两处路径修正：

- `path_config.PROJECT_ROOT` 改为本文件上两级目录，仍是仓库根；
- `time_schedule/get_time_tools.py`（当前没有调用方）改为 `from legacy.path_config import get_path`。

不要在运行代码里导入本目录；需要旧逻辑时先确认是否真的还需要。
