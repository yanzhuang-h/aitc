# tools：离线脚本

这里的脚本不参与生产运行，只在本地手工执行。请在**仓库根目录**用项目环境执行：

```bash
.venv/bin/python tools/config_check.py
.venv/bin/python tools/gen_online_config.py
.venv/bin/python tools/gen_api_docs.py
```

| 脚本 | 作用 | 产物 |
|---|---|---|
| `config_check.py` | 检查 `Lambdas.py` 中路口/设备映射配置的完整性（方向缺失、重复、未映射等） | 当前目录下 `lambda_config_check_report_<时间戳>.json` 与 `lambda_config_summary_<时间戳>.txt` |
| `gen_online_config.py` | 由 `lib/Global_intersection_coordinate` 的 `road_map`/`online_map_info` 计算互联网数据映射 | 当前目录下 `intersection_to_rid_lambda.py`、`new_online_data_map_lambda.py`；核对后手工合并进 `Lambdas.py`，不要提交（已在 `.gitignore` 中） |
| `gen_api_docs.py` | 生成《AITC 对外 HTTP 接口说明》Word 文档，依赖 `python-docx` | 仓库 `docs/对外HTTP接口说明.docx`，路径按脚本位置定位，与当前目录无关 |

## 调用链与配置只读审计

```bash
.venv/bin/python tools/control_config_audit.py --group 49
.venv/bin/python tools/control_config_audit.py --group 19 --roads 1700125
.venv/bin/python tools/control_config_audit.py --format json --output /tmp/aitc-audit-new.json
```

- 区分【历史组】、【19组】、【49组】的业务清单与实际分派入口，检查车道映射、方案相位、上下界、周期顺序和强制状态引用；不导入或执行生产模块，不修改配置。
- 默认只输出终端。`--output` 仅创建新的 JSON 报告，拒绝覆盖已有文件；JSON 包含配置来源摘要、路口入口清单及文件指纹，便于生产环境复核。
- 在线候选“具备选用条件”只表示代码接线、目标名单和开关满足要求，不证明经验表可用、实际下发或优化效果。读取白名单内的本地 `.env` 和环境开关，环境变量优先；配置审计固定读取 `--root` 仓库的 `lib` 文件，不读取外部数据路径或经验表。
- `warning` 是待核对疑点；重复相位、循环起点差异和历史专用相位不直接视为错误；逐方案覆盖提示须核对分时/专用方案含义。退出码：0 为没有结构错误（仍可能有警告），1 为发现结构错误，2 为输入不完整或报告写入失败。默认扫描包含尚未注册的上线清单项，不能把全部结果等同于在用方案故障。
- 三类调用链、保留规则及现场待核对事项统一沉淀到飞书 AITC 页面。生产补训仍使用对应日期的 `flow.txt` 与 `extend.txt`，本工具不替代补训或配时效果验证。

## 约定

- 脚本内部已把仓库根目录加入 `sys.path`，因此可以导入 `Lambdas` 与 `lib`；
  `config_check.py` 与 `gen_online_config.py` 读取的 `lib/*.json` 仍按进程工作目录解析，
  所以推荐在仓库根目录执行。
- 离线脚本不在服务启动路径中，改动后至少跑一次脚本本身确认可执行；审计工具另有自动化测试。
- 新增离线脚本一律放这里，根目录只保留运行入口与算法资产。
