"""最终配时的确定性检查结果；覆盖不完整不等于安全通过。"""

from typing import Literal
from pydantic import BaseModel, Field
from app.core.models.contract_types import CONTRACT_CONFIG, NonEmptyString
from .schemas import SignalPlan


class PlanSafetyResult(BaseModel):
    model_config = CONTRACT_CONFIG

    intersection_id: NonEmptyString
    status: Literal["valid", "partial", "no_action", "invalid"]
    plan: SignalPlan | None = None
    issues: list[str] = Field(default_factory=list)
    missing_rules: list[str] = Field(default_factory=list)

    @property
    def safe(self) -> bool | None:
        if self.status == "valid":
            return True
        if self.status == "invalid":
            return False
        return None
