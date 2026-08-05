# 数据底座

`infra/data` 是 AITC 重构中的数据底座。它会在保留现有模块运行方式的
前提下逐步接管数据接收、缓存、持久化和查询能力。

当前范围：

- 接收并持久化交通感知数据。
- 在内存中维护路口近期窗口数据。
- 持久化配置项。
- 持久化经验池数据。
- 为 Agent 和旧代码提供轻量 Python API。
- 按旧系统字段规则识别运行数据类型。
- 维护与旧系统兼容的 flow、queue、stage、extend、online、latest、radar、
  boyan 等窗口数据。
- 在日志格式迁移完成前，先包裹现有 `Write_to_file.py` 输出。
- 在不调整算法的前提下，先包裹现有 `Process_cache_data.py` 聚合函数。
- 在 `RuntimeDataReceiver` 中统一处理 TCP/HTTP 接收后的分类、写入、窗口缓存、
  雷达事件状态和溢出告警状态更新。

运行期数据默认写入 `infra/data/runtime/`，不应提交到 Git。
