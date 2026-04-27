"""BusinessContext, FocusArea, KPI, RiskFactor — 业务上下文模型."""

from __future__ import annotations

from typing import Tuple

from pydantic import BaseModel, Field


class KPI(BaseModel):
    """关键绩效指标."""

    name: str = Field(description="KPI 名称")
    direction: str = Field(
        default="higher_better",
        description="方向: higher_better | lower_better | stable",
    )
    description: str = Field(default="", description="指标说明")
    threshold: str = Field(default="", description="阈值/目标值")

    model_config = {"frozen": True}


class FocusArea(BaseModel):
    """关注领域."""

    area: str = Field(description="关注领域名称，如 '销售业绩'")
    kpis: Tuple[KPI, ...] = Field(
        default_factory=tuple, description="该领域的关键KPI"
    )
    weight: float = Field(default=1.0, description="领域权重")

    model_config = {"frozen": True}


class RiskFactor(BaseModel):
    """风险因素."""

    name: str = Field(description="风险名称")
    description: str = Field(default="", description="风险描述")
    threshold: str = Field(default="", description="触发阈值")
    severity: str = Field(default="medium", description="严重程度: low | medium | high")

    model_config = {"frozen": True}


class BusinessContext(BaseModel):
    """事业部业务上下文."""

    department: str = Field(description="事业部名称")
    description: str = Field(default="", description="事业部简介")
    focus_areas: Tuple[FocusArea, ...] = Field(
        default_factory=tuple, description="关注领域列表"
    )
    terminology: Tuple[str, ...] = Field(
        default_factory=tuple, description="行业术语"
    )
    content_expectations: Tuple[str, ...] = Field(
        default_factory=tuple, description="内容期望"
    )
    risk_factors: Tuple[RiskFactor, ...] = Field(
        default_factory=tuple, description="常见风险因素"
    )
    analysis_prompt_extension: str = Field(
        default="", description="Claude system prompt 的业务上下文扩展"
    )

    model_config = {"frozen": True}

    def to_prompt_text(self) -> str:
        """生成注入 Claude prompt 的业务背景文本."""
        parts = [f"## {self.department}\n"]
        if self.description:
            parts.append(f"{self.description}\n")

        if self.focus_areas:
            parts.append("### 关注领域")
            for fa in self.focus_areas:
                kpi_text = ", ".join(
                    f"{k.name}({k.direction})" for k in fa.kpis
                )
                parts.append(f"- {fa.area}: {kpi_text}")

        if self.terminology:
            parts.append(f"\n### 行业术语\n{', '.join(self.terminology)}")

        if self.content_expectations:
            parts.append("\n### 内容期望")
            for ce in self.content_expectations:
                parts.append(f"- {ce}")

        if self.risk_factors:
            parts.append("\n### 常见风险")
            for rf in self.risk_factors:
                parts.append(f"- [{rf.severity}] {rf.name}: {rf.threshold}")

        if self.analysis_prompt_extension:
            parts.append(f"\n{self.analysis_prompt_extension}")

        return "\n".join(parts)
