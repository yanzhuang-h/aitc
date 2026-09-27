# 运行数据字段字典（MVP 版）

> 本文解释服务端与上游对接的原始字段含义，供阅读与排查时查阅。
>
> - 字段名是**上游系统协议约定**（信控平台 / 雷达 / 博研），服务端只读不改；
> - 多数缩写为国内交通行业**拼音缩写惯例**；
> - 本版为最小可用字典：标注 ⚠️ 的为**推断**，待数据或文档核实后收敛；
> - 与契约文档配套阅读：`todo-done/data-contract.md`（11 类数据的最小字段表）。

## 1. 通用时间与系统字段

| 字段 | 含义 | 示例 | 出现位置 |
| --- | --- | --- | --- |
| `ts` | 事件发生时刻，毫秒 epoch | `1785255292677` | flow / overflow_warning / radar / boyan |
| `time` | 事件发生时刻，毫秒 epoch | 同上 | stage |
| `start_time` | 排队开始时刻，毫秒 epoch | 同上 | queue |
| `createTime` | 事件创建时刻：雷达事件为 `%Y-%m-%d %H:%M:%S` 字符串；溢出合并后为秒级字符串 | `2026-09-24 10:00:00` | radar_event / 溢出结果 |
| `received_at` | 服务端接收时刻（UTC ISO） | `2026-09-24T14:23:43+00:00` | 仓库补充，非上游字段 |
| `AITC_SYS_TS` | 写入日志时补的秒级时间戳 | `1790432534` | 本系统补充 |

## 2. flow（过车记录，TCP）

| 字段 | 全拼 | 含义 | 备注 |
| --- | --- | --- | --- |
| `jtll_ddbh` | 交通流量·地点编号 | 检测器（点位）编号，靠 `location_to_intersection_lambda` 挂到路口 + 方向 | 代码注释证实 |
| `ycsb_cdbh` | 车道编号 | 该记录累加到哪个车道 | 代码注释证实 |
| `ycsb_xsfx` | 行驶方向 | 方向/流向代码（如 `"1A"`） | 具体编码待补 |
| `ycsb_xssd` | 行驶速度 | 单车速度 | |
| `ycsb_cthphm` | 车头牌号码 | 车牌号，追溯用 | |
| `ycsb_cpzxd` | 车平均速度 | 值形如 `0.88` | ⚠️ |

## 3. queue（排队数据，TCP）

| 字段 | 含义 | 备注 |
| --- | --- | --- |
| `car_nums` | 排队明细列表 | 元素结构见下 |
| `car_nums[].ycsb_cdbh` | 车道编号 | |
| `car_nums[].queue` | 排队长度 | ⚠️ |
| `car_nums[].all` | 车道车辆总数 | ⚠️ |

## 4. stage / extend（相位状态，TCP）

| 字段 | 含义 | 备注 |
| --- | --- | --- |
| `CrossId` | 路口编号 | |
| `curStageNo` | 当前阶段号 | |
| `curStageLen` | 当前阶段时长（已放行） | |
| `curStageRemainLen` | 当前阶段剩余时长 | extend 无时间字段，窗口用到达时间 |

## 5. online / latest（互联网与最新数据，TCP）

| 字段 | 含义 | 备注 |
| --- | --- | --- |
| `rid` | 路段编号 | 由 `online_data_map_lambda` 挂到路口 ⚠️ |
| `inter_id` | 路口编号 | 由 `latest_data_map_lambda` 校验 |

## 6. overflow_warning（溢出告警，TCP）

| 字段 | 含义 | 备注 |
| --- | --- | --- |
| `distance` | 溢出距离（米） | 写入 `overflow_warning_map[路口][方向]` ⚠️ |
| `jtll_ddbh` | 检测器编号 | 用于定位路口与方向 |
| `ts` | 告警发生时刻（毫秒） | |

## 7. radar / radar_event / boyan（HTTP）

| 字段 | 含义 | 备注 |
| --- | --- | --- |
| `deviceNo` | 雷达设备编号 | 由 `device_to_location` 挂到路口 + 方向 |
| `eventType` | 事件类型 | `OverFlow` 溢出 / `QueueOverrun` 排队溢出 / `Parking` 违停 / `Speeding` 超速（见 `Lambdas.py`） |
| `carNums` | 雷达帧内车辆数 | ⚠️ |
| `deviceId` | 博研设备编号 | 由 `boyan_device_to_location` 挂到路口 + 方向 |

## 8. 方向与编号约定

- 方向代码：`U` 上 / `D` 下 / `L` 左 / `R` 右；`traffic_vector` 固定顺序 `[L, R, U, D]`。
- 编号体系：`aibi_to_xinkongji` 把爱博路口编号换算成信控机编号。

## Backlog（暂不实施）

- 内部时间归一化：落库时补统一 `event_ts` 字段，收敛 `ts` / `time` / `start_time` / `createTime` 的差异（2026-09-27 讨论决定：先不做，记录于此）。
- ⚠️ 字段含义待核实项：`ycsb_cpzxd`、`rid`、`distance`、`carNums`、`car_nums[].queue/all`。
