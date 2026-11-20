# offline_tools 独立离线制表

使用本目录的路口配置和历史日志独立生成经验表。训练报告和候选数据可以在本地复查，`--merge` 默认更新本目录的离线经验表。

~~~bash
python3 offline_tools/import_logs.py --help
python3 offline_tools/offline_train.py --help
~~~

| 路径 | 用途 |
|---|---|
| `import_logs.py` | 校验并归档历史 FLOW 和 EXTEND，支持复制、移动或建立软链接 |
| `offline_train.py`、`offline_trainer/` | 估计通行能力、补齐绿灯秒数并生成训练报告 |
| `configs/cross_info.json` | 独立路口配置 |
| `logs_data/flow/`、`logs_data/extend/` | 历史训练输入 |
| `logs_data/offline_training/` | 训练报告和候选经验 |
| `experience_pool/offline_experience.json` | 独立离线经验表 |
| `offline_trainer/phase_definitions.py` | 离线训练与实时配时共用的相位定义 |

生产在线经验的自动补跑和手动补训见 [维护脚本](../tools/README.md#生产环境经验补训与只读诊断)。
配置检查、在线映射生成和接口文档生成的旧命令转发到 `tools/`。
