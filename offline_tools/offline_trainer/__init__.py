"""AITC 完全独立的离线学习模块 (Self-contained Offline Trainer).

特性：
- 零外部系统依赖，纯 Python 原生标准库实现；
- 包含完整的日志清洗、周期识别、E_T 容量计算、单调补气插值与结构校验；
- 产出可作为初始表安全合并入 offline_experience.json。
"""

from .pipeline import (
    check_input_data_availability,
    resolve_date_list,
    run_offline_pipeline,
)
from .validator import (
    ExperienceValidationError,
    merge_experience_tables,
    validate_experience_table,
)

__all__ = [
    "ExperienceValidationError",
    "check_input_data_availability",
    "merge_experience_tables",
    "resolve_date_list",
    "run_offline_pipeline",
    "validate_experience_table",
]
