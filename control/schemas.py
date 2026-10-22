"""控制边界契约；安全约束由独立 Safety Gate 判定。"""

from typing import Annotated

from pydantic import BaseModel, Field

from app.core.models.contract_types import CONTRACT_CONFIG, FiniteNumber, NonEmptyString


PhaseDuration = Annotated[FiniteNumber, Field(ge=0)]


class SignalPlan(BaseModel):
    """保留八个相位槽、保留位及方案号，不提前截断或取整。"""

    model_config = CONTRACT_CONFIG

    intersection_id: NonEmptyString
    phase_times: Annotated[tuple[PhaseDuration, ...], Field(min_length=8, max_length=8)]
    reserved: FiniteNumber
    program_id: FiniteNumber | NonEmptyString
