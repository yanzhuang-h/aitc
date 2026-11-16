"""运行与训练共同使用的相位语义；定义置于可独立分发的离线算法包。"""

# 兼容从 lib/data_ANS 目录直接运行训练脚本。
if not __package__:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from offline_tools.offline_trainer.phase_definitions import PHASE_DIRECTION_MAP
