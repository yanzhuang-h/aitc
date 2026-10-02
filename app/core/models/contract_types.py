"""边界契约共用的校验规则，不做隐式数值转换。"""

from typing import Annotated

from pydantic import ConfigDict, Field, StrictFloat, StrictInt


CONTRACT_CONFIG = ConfigDict(
    strict=True, extra="forbid", allow_inf_nan=False,
    validate_assignment=True, revalidate_instances="always",
)
NonEmptyString = Annotated[str, Field(min_length=1, pattern=r"\S")]
FiniteNumber = StrictInt | StrictFloat
Timestamp = Annotated[FiniteNumber, Field(ge=0)]
