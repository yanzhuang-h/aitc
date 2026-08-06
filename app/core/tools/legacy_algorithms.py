"""旧算法加载适配层。

部分历史算法模块在导入时会直接向控制台输出调试信息。这里集中做一次
静默加载，避免服务启动日志被旧模块的导入副作用打散。
"""

from __future__ import annotations

import contextlib
import io


with contextlib.redirect_stdout(io.StringIO()):
    from lib.DQN_Select import DQN_select


__all__ = ["DQN_select"]
