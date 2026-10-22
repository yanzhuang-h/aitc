"""隔离 LangGraph UUID 随机源，保留旧算法与格式器的随机序列。"""

import random

from langgraph.checkpoint.base import id as checkpoint_ids


def isolate_checkpoint_randomness() -> None:
    # langgraph 1.2.12 / checkpoint 4.2.0 即使没有 saver，也每步生成 UUIDv6。
    # 默认 getrandbits 会推进旧算法的全局 random；只替换这个依赖模块的引用。
    # 不能在每次调用恢复 random 状态，否则会回滚 selector 且破坏并发调用。
    if checkpoint_ids.random is random:
        checkpoint_ids.random = random.SystemRandom()
