# tools：手动维护脚本

维护脚本按需手动运行。配置检查、在线映射生成和接口文档生成在**源码仓库根目录**用项目环境执行。

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

服务自动补跑缺失日期。手动补训通过同一在线经验池处理生产保存的同日 FLOW 和 EXTEND。独立离线制表见 [offline_tools](../offline_tools/README.md)。

~~~bash
# 预览过去7个完整日，不含当天；默认19组＋已登记的平台路口
.venv/bin/python tools/backfill_experience.py

# 在生产版本目录执行，积累经验并按原质量门槛发布
.venv/bin/python tools/backfill_experience.py --apply

# 只读核查任务记录、发布文件、当前配置的读取表和最近候选日志
.venv/bin/python tools/check_online_learning.py --cross 1700125 --cross 1700240
~~~

- 读取版本目录的.env，环境变量优先；打印实际发布表、版本清单及逐日输入/任务报告路径。--root可指定版本目录，相对路径以该目录为准。
- 手动日期默认昨天结束，向前七天，也可用 `--days` 或 `--start/--end`。生产默认在启动 5 分钟后及每天中午 12:00 按日期从旧到新重查截至昨天的最近 10 天。11 月 19 日启动时覆盖 11 月 9–18 日。显式设置 `AITC_EXPERIENCE_POOL_INITIAL_DELAY_SECONDS=0` 时仅运行中午任务。
- 补训启动后，终端按已检查的来源日显示进度条。`[###-------] 已检查 3/10` 表示已检查三天，各行同时显示发布、复用或待收齐状态。后台可在 `server.log` 查看。
- 自动处理要求同日 `FLOW` 和 `EXTEND` 都存在，其尾部落盘记录在日末最后一个学习窗口内。待收齐的日期记录在 `experience_pool_catchup` 日志中。复用历史报告时，日更及补跑日志标为 `reused_existing_report`，`table_updated` 表示本次执行是否发布。
- `--roads online` 覆盖【19组】和本地已登记的平台路口。也可指定 `19`、`49` 或路口编号列表。旧 `all` 按 `plan_id_overrides.json` 的全部路口键处理。
- 预览显示所选路口总数和各范围计数，并按自动补跑的日末检查逐日提示缺文件、未收齐或无法读取。
- 正式门槛默认30样本。缺文件、缺配置等跳过会在报告说明，执行结束返回非零；零候选及未达到发布门槛不伪装为已发布。
- `--force` 在锁内复查日记录，已入池样本继续去重。若某路口已有更晚入池记录，该路口在对应旧日进入 `rebuild_required_roads`，其余路口继续。待重建路口用保留基表按日期重建。
- `run_experience_pool_now.py` 复用同一实现并立即执行，默认 T-1、30 样本和 19 组＋平台路口。正式周补训使用上述入口。
- 诊断逐行扫描日志，分别显示阶段反馈达标情况与窗口内 FLOW 时间点数，并核对最近七个完整日的运行记录与范围、发布表与清单指纹、分配器配置读取路径和最新日志经验指纹。路径不同可能是有意对照，指纹不同也可能是日志早于文件更新；需结合时段判断，不能单凭诊断证明另一进程已加载或信号机已执行。
- 生产补训完成后回传终端输出及输出中列出的逐日报告；正常部署排查仍沿用[运维与问题](https://dkrg-heu.feishu.cn/wiki/MYYgwcG52iK4rjk0gTkcTaddnCc)的回传流程。

## 20—30分钟短时试运行

沿用原部署方式正常运行20—30分钟，本次不手动补训。打包回传运行当天：

- 版本目录下的 server.log。
- logs_data/send/日期_send.txt。
- logs_data/shadow/flow_time_allocator_日期.jsonl。
- logs_data/flow/日期_flow.txt。
- logs_data/extend/日期_extend.txt。
- logs_data/queue/日期_queue.txt，如当天没有生成则注明。

备注起止时间，以及【19组】1700125、【49组】1700240/2704746的实际下发开关状态；若期间改过配置，附路口、方案、操作时间和前后值。无需为取日志额外切换开关或重复修改最小绿。

运行日志中的aitc.decision_batch.input_timebase每批对照FLOW.ts、EXTEND.time与缓存入库时间；它是聚合前快照摘要，入库时间发生在原落盘之后，不是精确socket接收时间。时间倒退/重复按每路口到达顺序统计，多检测器汇合也可能出现，需结合原始文件判断。此摘要与现有候选、配置、预算、格式化和发送指纹共同定位问题，不证明报文字段的业务语义或信号机执行。

正常打包流程的编译产物回归通过后，可交运维短时试运行；本次用于获取诊断证据，正式补训仍待生产完整数据，全天高峰效果另行验收。

## 新路口本地登记

双方配置同步后，我方先预览检测器、阶段、方案和时长。预检通过后写入本地登记。

~~~bash
.venv/bin/python tools/onboard_intersection.py --cross 999999
.venv/bin/python tools/onboard_intersection.py --cross 999999 --apply
~~~

- 新路口只写入 `lib/plan_id_overrides.json` 的本地登记，服务启动时从 `cross_info` 和 `road_info` 推导数据源、设备映射和配时入口。
- 新路口自动进入默认在线候选和经验积累范围；如部署显式限定了 AITC_FLOW_ALLOCATOR_PILOT_ROADS、AITC_EXPERIENCE_POOL_ROADS、AITC_EXPERIENCE_TABLE_UPDATE_ROADS，仍按现场白名单执行，需同步追加。
- 不要求预先制作离线经验。上线起运行并积累经验；两周左右是业务预期，不是定时启用条件，经验发布仍遵守现有质量与样本门槛。
- 检测器归属冲突、默认方案无效、阶段未定义或时长边界冲突会在写入前报错。周期与方案顺序待核对时，预览会明确提示。
- --program-id 可指定 road_info 中已有的方案。省略时保留已登记的默认方案，首次登记取第一个状态键。--template 保留旧命令默认值。
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
