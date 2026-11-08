# tools：离线脚本与辅助工具集

这里的脚本不参与生产实时运行，供本地或运维离线手工执行。请在**仓库根目录**执行：

```bash
python3 offline_tools/offline_train.py --help
python3 offline_tools/import_logs.py --help
python3 offline_tools/config_check.py
python3 offline_tools/gen_online_config.py
python3 offline_tools/gen_api_docs.py
```

## 工具清单

| 脚本 | 作用 | 核心产物 / 行为 |
|---|---|---|
| `offline_train.py` | **离线训练快捷入口**：调用完全独立的 `offline_trainer`，从历史数据中计算通行能力、补齐绿灯秒数并合并入独立经验表 | 训练报告输出在 `offline_tools/logs_data/offline_training/`；若加 `--merge` 则合并入独立的 `offline_tools/experience_pool/offline_experience.json` |
| `import_logs.py` | **历史日志导入与标准化工具**：扫描外部导出的原始 flow / extend 日志，自动识别日期、格式校验，并归档至 `logs_data/` | 标准化放置在 `logs_data/flow/` 和 `logs_data/extend/`（支持复制、移动或建立软链接） |
| `config_check.py` | 检查 `Lambdas.py` 中路口/设备映射配置的完整性（方向缺失、重复、未映射等） | 当前目录下 `lambda_config_check_report_<时间戳>.json` 与 `lambda_config_summary_<时间戳>.txt` |
| `gen_online_config.py` | 由 `lib/Global_intersection_coordinate` 的 `road_map`/`online_map_info` 计算互联网数据映射 | 当前目录下 `intersection_to_rid_lambda.py`、`new_online_data_map_lambda.py`；核对后手工合并进 `Lambdas.py`，不要提交（已在 `.gitignore` 中） |
| `gen_api_docs.py` | 生成《AITC 对外 HTTP 接口说明》Word 文档，依赖 `python-docx` | 仓库 `docs/对外HTTP接口说明.docx`，路径按脚本位置定位，与当前目录无关 |

## 目录结构说明

```text
offline_tools/
├── offline_trainer/        # 离线核心算法包（纯 Python 算法代码，供未来单独编译/混淆加密）
├── configs/                # 【独立路口配置目录】（明文配置，便于用户随时编辑或替换）
│   └── cross_info.json     # 路口静态拓扑配置文件
├── logs_data/              # 独立日志数据与训练质检产物
│   ├── flow/               # 流量输入数据
│   ├── extend/             # 信控输入数据
│   └── offline_training/   # 训练产物与审计清单
├── experience_pool/        # 独立离线经验底表
│   └── offline_experience.json
├── offline_train.py        # 离线训练执行入口
├── import_logs.py          # 日志标准化导入工具
├── config_check.py         # Lambdas 配置完整性检查
├── gen_online_config.py    # 互联网地图映射生成
└── gen_api_docs.py         # 接口文档生成
```

## 约定

- 脚本内部已把仓库根目录加入 `sys.path`，因此可以直接在项目根目录下通过 `python3 offline_tools/<脚本名>.py` 执行。
- 脚本不在实时服务核心启动路径里，改动后至少跑一次脚本本身确认可执行。
- 新增离线管理脚本一律放这里，根目录只保留核心服务运行入口。
