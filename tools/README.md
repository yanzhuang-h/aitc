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

## 约定

- 脚本内部已把仓库根目录加入 `sys.path`，因此可以导入 `Lambdas` 与 `lib`；
  `config_check.py` 与 `gen_online_config.py` 读取的 `lib/*.json` 仍按进程工作目录解析，
  所以推荐在仓库根目录执行。
- 三个脚本都不在服务启动路径和测试套件里，改动后至少跑一次脚本本身确认可执行。
- 新增离线脚本一律放这里，根目录只保留运行入口与算法资产。
