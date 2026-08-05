# 运行数据契约

本文定义数据底座接收的数据类型、来源及最小字段。当前为兼容旧系统，契约校验是非阻断式：不合格数据仍可进入既有分类链路，但接入方应以此修复数据质量问题。

| 类型 | 来源 | 最小字段 | 时间字段 | 路口识别 |
| --- | --- | --- | --- | --- |
| `flow` | TCP | `ycsb_xsfx`, `jtll_ddbh`, `ycsb_cdbh`, `ts` | `ts`，毫秒 | `CrossId` / `intersection_id` / 检测器编号 |
| `queue` | TCP | `jtll_ddbh`, `start_time`, `car_nums` | `start_time`，毫秒 | `CrossId` / `intersection_id` / 检测器编号 |
| `stage` | TCP | `CrossId`, `time`, `curStageNo`, `curStageLen` | `time`，毫秒 | `CrossId` |
| `extend` | TCP | `CrossId`, `curStageRemainLen` | 无 | `CrossId` |
| `online` | TCP | `rid` | 无 | 由 `rid` 配置映射 |
| `latest` | TCP | `inter_id` | 无 | `inter_id` |
| `heartbeat` | TCP | `heartbeat` | 无 | 无 |
| `overflow_warning` | TCP | `distance`, `jtll_ddbh`, `ts` | `ts`，毫秒 | 检测器编号 |
| `radar` | HTTP | `deviceNo` | 可选 `ts` | 由设备配置映射 |
| `radar_event` | HTTP | `deviceNo`, `eventType` | 可选 `createTime` | 由设备配置映射 |
| `boyan` | HTTP | `deviceId` | 可选 `ts` | 由设备配置映射 |

统一规则：

- 接收来源仅为 `tcp`、`http` 或 `unknown`；运行服务会使用前两者。
- 毫秒时间戳应可被 `int()` 转换。接收时间由仓库统一记录为 UTC `received_at`。
- `RuntimeRecord` 的持久化结构固定为 `kind`、`payload`、`intersection_id`、`source`、`received_at`。
- 未识别载荷按 `history` 保存，不声明强制字段，便于回放和后续新增类型。
