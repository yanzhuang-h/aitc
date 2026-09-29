# Day 2 学习笔记：数据底座 `infra/data`

> 目标：说清一条数据进来后的每一步，以及「窗口 / 仓库 / 输出」三者的分工。
> 配套：`todo-done/data-contract.md`（11 类数据契约）、`docs/field-dictionary.md`（字段字典）、`docs/backlog.md`。

## 一、一条数据进来的完整路径

```text
TCP 65432 / HTTP 8088
  → RuntimeDataIngestor（贴来源标签）
  → RuntimeDataReceiver.receive()
      ① classify_data 字段指纹分类（11 类 + history 兜底）
      ② validate_contract → DataQualityMonitor（非阻断，只告警）
      ③ writer 写旧格式日志 logs_data/<类别>/日期_类别.txt（补 AITC_SYS_TS）
      ④ repository 写长期仓库 runtime/runtime/<kind>.jsonl（解析 intersection_id）
      ⑤ _update_runtime_state：进窗口（部分需白名单）/ 溢出表 / 雷达事件表
```

## 二、三者的分工（关键结论）

| 存储 | 语义 | 消费者 | 替换方向 |
| --- | --- | --- | --- |
| 短窗 ShortTermMemory | 时间序列（600s/240s/1800s…） | 决策聚合 + MemoryQueryLayer | Redis |
| 长仓 LongTermMemory | 可追溯历史（每类 10000 条裁剪） | MemoryQueryLayer + Agent 工具 | SQLite |
| 结果仓库 ResultWarehouse | 最新一轮方案快照 | TCP 广播线程 + 查询层 | Redis |

- 溢出告警 / 雷达事件不进窗口：状态语义（原地覆盖），非时间序列。
- 白名单：未注册设备数据入库但不进窗口（可追溯、不上桌）。
- `JsonFileStore`：追加 JSONL + 裁剪原子替换（temp + fsync + os.replace）；`write_json` 已改原子写。

## 三、当天自答题答案

1. **新增一种数据类型改哪几处**：classifier（枚举+指纹）→ contracts（契约条目）→ receiver（状态分支）→ data-contract.md；按需再加窗口时长 / 日志类别映射 / 聚合函数。
2. **溢出与雷达事件为何不进窗口**：窗口=序列（追加聚合），状态=覆盖（只关心最新）；混用会污染聚合。
3. **窗口与仓库分别被谁读**：窗口→决策聚合 + 查询层；长仓→查询层 + Agent 工具；结果仓→广播线程 + 查询层。
4. **换 Redis 动哪里**：只动 `memory/short_term.py`、`repository.py`+`storage.py`、`result_warehouse.py` 三个实现，调用方零改动。

## 四、当天落地

- PR #20 字段字典 MVP（`docs/field-dictionary.md`）；PR #21 数据层精简（删 Traffic 旁路/死代码、配置写原子化）；PR #22 Backlog 清单（A/B/C/D 四组）。
- 观察项（入 Backlog）：`event_ts` 时间归一、`heartbeat`/`latest` 无消费者、两套写入收敛、`intersection_fields` 无读者等。
