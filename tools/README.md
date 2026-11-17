# tools：手动维护脚本

脚本由维护人员在本地或生产版本目录按需执行，不由服务自动调用。请在**版本目录**用项目环境执行：

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

## 生产环境经验补训与只读诊断

正式补训使用生产保存的flow/extend。本地数据用于解析、筛选和配时回归，不能代表完整训练效果。

~~~bash
# 预览过去7个完整日，不含当天；默认19组＋已登记的平台路口
.venv/bin/python tools/backfill_experience.py

# 在生产版本目录执行，积累经验并按原质量门槛发布
.venv/bin/python tools/backfill_experience.py --apply

# 只读核查任务记录、发布文件、当前配置的读取表和最近候选日志
.venv/bin/python tools/check_online_learning.py --cross 1700125 --cross 1700240
~~~

- 读取版本目录的.env，环境变量优先；打印实际发布表、版本清单及逐日输入/任务报告路径。--root可指定版本目录，相对路径以该目录为准。
- 日期默认昨天结束，向前七天；也可用--days或--start/--end。服务原有每天12:00处理T-2的调度不变，没有新增后台补跑。
- --roads online为19组和本地已登记的平台路口；19/49为批次，也可填ID列表。旧all仍只取plan_id_overrides.json登记，通常仅49组，不把旧命令悄悄扩成全部路口。
- 正式门槛默认30样本。缺文件、缺配置等跳过会在报告说明，执行结束返回非零；零候选及未达到发布门槛不伪装为已发布。
- --force仅在锁内复查日记录，已入池样本仍去重；它不清空样本池、不重新混合已处理路口，也不代替历史重建。若旧日期早于该路口已入池日期，原时间顺序约束仍会阻止倒序补入，需按保留基表另行制定重建方案。
- run_experience_pool_now.py保留单日手动入口并复用同一实现；立即执行的语义不变，默认改为T-2、30样本和19组＋平台路口。正式周补训统一使用上述入口。
- 诊断逐行扫描日志，检查最近七个完整日的运行记录与范围、发布表与清单指纹、分配器配置读取路径和最新日志经验指纹。路径不同可能是有意对照，指纹不同也可能是日志早于文件更新；需结合时段判断，不能单凭诊断证明另一进程已加载或信号机已执行。
- 生产补训完成后回传终端输出及输出中列出的逐日报告；正常部署排查仍沿用[运维与问题](https://dkrg-heu.feishu.cn/wiki/MYYgwcG52iK4rjk0gTkcTaddnCc)的回传流程。

## 新路口本地登记

平台同步 cross_info / road_info 后，我方先预览，再确认写入本地登记：

~~~bash
.venv/bin/python tools/onboard_intersection.py --cross 999999
.venv/bin/python tools/onboard_intersection.py --cross 999999 --apply
~~~

- 保留本地登记步骤。脚本只更新数据源、设备映射、控制类别、平台相位策略和默认方案号，不再克隆路口配时函数。
- 新路口自动进入默认在线候选和经验积累范围；如部署显式限定了 AITC_FLOW_ALLOCATOR_PILOT_ROADS、AITC_EXPERIENCE_POOL_ROADS、AITC_EXPERIENCE_TABLE_UPDATE_ROADS，仍按现场白名单执行，需同步追加。
- 不要求预先制作离线经验。上线起运行并积累经验；两周左右是业务预期，不是定时启用条件，经验发布仍遵守现有质量与样本门槛。
- --program-id 可指定 road_info 中的默认方案号；不填时沿用脚本原有选择规则。--template 仅保留旧命令默认值兼容，不再生成模板副本。
- 脚本写入后完成回归、走 PR；打包与部署另行决定。

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

## 生产基线回放结果对比

两个版本分别使用相同输入、决策时间、随机种子和配置回放后，比较其单模式输出目录：

```bash
.venv/bin/python tools/compare_release_replays.py \
  --baseline /tmp/old-replay/baseline \
  --candidate /tmp/new-replay/baseline \
  --output /tmp/release-comparison-new.json
```

- 每个目录须包含现有回放工具生成的 results.jsonl 和 summary.json。比较只读取这两个文件，不运行服务或修改配置；输出报告仅创建新文件。
- 首先核对已记录的输入指纹、读取范围、配置指纹、随机种子、时间线和记录计数；不匹配时标记 incomparable。外部预测目录没有内容指纹，不能据路径相同认定条件一致。summary.json 未记录的输入通道、时刻表、环境与配置仍需独立核对，不能据本工具自动批准发布。
- 逐路口区分【历史组】、【19组】、【49组】，列出新增、缺失、控制方案、其他报文字段和公共路口顺序变化；数值类型变化（20 与 20.0）也记录。
- 【历史组】差异需要核查是否回归；【19组】【49组】差异仅表示待验收。两组即使输出相同，也不表示已有问题已解决；未覆盖的组返回 null，不记为通过。
- 退出码：0 仅表示已记录条件匹配且样本输出一致，1 表示有差异或条件不匹配，2 表示输入无效或报告无法写入。样本一致不等于现场效果或完整发布验收通过。

## 约定

- 脚本内部已把仓库根目录加入 `sys.path`，因此可以导入 `Lambdas` 与 `lib`；
  `config_check.py` 与 `gen_online_config.py` 读取的 `lib/*.json` 仍按进程工作目录解析，
  所以推荐在仓库根目录执行。
- 维护脚本不在服务启动路径中；改动后验证脚本入口和必要测试，正式补训仅在生产数据具备时执行。
- 新增离线脚本一律放这里，根目录只保留运行入口与算法资产。
