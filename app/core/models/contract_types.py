"""边界契约共用的校验规则，不做隐式数值转换。"""

from typing import Annotated

from pydantic import ConfigDict, Field, StrictFloat, StrictInt


def _compiled_probe() -> None:
    """占位函数：本模块编译为 .so 后，它的类型是 cython_function_or_method。"""


# Cython 会把类方法编译成 cython_function_or_method，pydantic 2 会把它误判成未注解的
# 字段并拒绝建模。把该类型声明进 ignored_types，源码运行与 .so 运行都能正常建模。
CYTHON_METHOD_TYPES = (type(_compiled_probe),)

CONTRACT_CONFIG = ConfigDict(
    strict=True, extra="forbid", allow_inf_nan=False,
    validate_assignment=True, revalidate_instances="always",
    ignored_types=CYTHON_METHOD_TYPES,
)
NonEmptyString = Annotated[str, Field(min_length=1, pattern=r"\S")]
FiniteNumber = StrictInt | StrictFloat
Timestamp = Annotated[FiniteNumber, Field(ge=0)]
