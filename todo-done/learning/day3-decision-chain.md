# Day 3 学习笔记：决策链路与算法边界

> 目标：说清 50s 周期内每一步，以及每个 `lib` 入口的输入输出。

## 一、`run_once()` 五步

```text
① _process_data：窗口聚合 → 186 路口并发决策（线程池 30）
② 快照（可选）+ coordinate() 全局协调
③ phase_check() 相位时长校验 + 报告落盘
④ 组装：format_result 打包下发协议
⑤ result_warehouse.replace()（广播线程负责发）
```

- 全路口成功才协调；任一失败降级为"只校验+直发"。
- DQN 调用已统一走 `IntersectionControlRequest` → `call_dqn_select()`（PR #27）。

## 二、DQN 真相（"DQN"实为规则启发式）

- 入口 `DQN_select(15 参数)`：白名单 `Cross_Video`（65 个）逐路口分发，其余返回全 0。
- 路口函数 4 种模式：雷达数车 / 视频 predict_head / 流量 chuli_shuju / 空壳；签名 4 种（10/11/12/14 参）——统一方案见 Backlog D1。
- 核心公式：**当前小时基准 `sch` + 实时窗口增量 → Ng/Define_road_pass 夹限**。
- `get_exp` 只把状态打成 30 位样本；`get_model_map` 含随机 score（旧行为）。

## 三、全局协调 `coordinate()`

1. 三类处理器：`intern_road_id`(133) / `video_road`(3) / `video_flow_road`(52) + `aibi_road`(1)；
2. 特殊路口调整（se_map=10）+ 最小周期补全（全体）；
3. 绿波走廊（当前 1 条 lvbo_01，4 路口）链式拥堵传播；
4. `int` 取整 + 浮动值应用。

- 清单关系：186 总清单 ⊃ 并集 177（有类别）；9 个无类别（7 纯 DQN + 2 无处理）；Cross_Video(65) 与各类别大量重叠。
- 经验池现状：在线产样本（logs_data/EXP）→ 调度器每日沉淀 `lib/experience_pool/` 滚动表 → **在线决策尚未消费经验表**（闭环待接通，见 D3/D5）。

## 四、预测链路（管道已接、消费未开）

- 每 50s 写样本 flow_pre/queue_pre；每日 03:00 同型日（工作日 10 天/周末 3 天）10 分钟窗口平均 → 每日预测 json；
- 决策时取当前 10min 窗预测，文件缺失返回 None 不阻断；
- **路口函数签名收 `cur_flow_pre_map/cur_queue_pre_map` 但函数体零使用**——预测接入属于 D5 范围。

## 五、当天自答题答案

1. **一轮决策输入/输出**：输入=窗口快照+两个预测+上一轮协调集+溢出/事件状态+当前时间；输出写 5 处（结果仓库→广播、经验样本 EXP、预测样本 flow_pre/queue_pre、相位校验报告、可选控制快照）。
2. **EXP_list 给谁用**：落盘 → 调度器每日离线沉淀/校验激活滚动经验表；在线侧目前只产不读。
3. **相位校验拦什么**：方案号缺失跳过（status=2）、时长越界原地夹到 [min,max]、遇 0 停止；**不拦**相位数量一致性，且只修正不告警拒绝。
4. **预测缺失降级**：返回 None 不阻断；当前预测参数函数体零使用，缺失对方案零影响。

## 六、当天落地

- PR #23 Backlog+A5/D3/D4；#24 shipin→video 改名；#25 删旧脚本+D5；#27 DQN 参数接口统一+命名规范；#28 D1 细化。
