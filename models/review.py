"""ReviewReport, FormatIssue, ContentIssue, AIReport — 审核结果模型."""

from __future__ import annotations

from typing import Optional, Tuple

from pydantic import BaseModel, Field


class FormatIssue(BaseModel):
    """单个格式问题."""

    page_number: int = Field(description="问题所在页码")
    category: str = Field(
        description="问题类别: font | size | color | layout | margin"
    )
    severity: str = Field(
        default="warning", description="严重程度: error | warning | info"
    )
    message: str = Field(description="问题描述")
    detail: dict = Field(
        default_factory=dict, description="详细信息 (实际值/期望值等)"
    )
    text_snippet: str = Field(default="", description="相关的文字片段")

    model_config = {"frozen": True}


class ContentIssue(BaseModel):
    """单个内容问题."""

    type: str = Field(
        description="问题类型: missing_section | order_error | insufficient_content | missing_element"
    )
    severity: str = Field(
        default="warning", description="严重程度: critical | error | warning | info"
    )
    section_id: str = Field(default="", description="相关章节ID")
    section_name: str = Field(default="", description="章节名称")
    message: str = Field(description="问题描述")
    detail: dict = Field(default_factory=dict)

    model_config = {"frozen": True}


class FormatReport(BaseModel):
    """格式审核报告."""

    total_issues: int = Field(default=0)
    issues: Tuple[FormatIssue, ...] = Field(default_factory=tuple)
    font_score: float = Field(default=1.0, ge=0.0, le=1.0)
    size_score: float = Field(default=1.0, ge=0.0, le=1.0)
    color_score: float = Field(default=1.0, ge=0.0, le=1.0)
    layout_score: float = Field(default=1.0, ge=0.0, le=1.0)
    overall_score: float = Field(default=1.0, ge=0.0, le=1.0)

    model_config = {"frozen": True}

    def get_issues_by_severity(self, severity: str) -> Tuple[FormatIssue, ...]:
        return tuple(i for i in self.issues if i.severity == severity)


class ContentReport(BaseModel):
    """内容审核报告."""

    total_issues: int = Field(default=0)
    issues: Tuple[ContentIssue, ...] = Field(default_factory=tuple)
    section_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    essential_complete: bool = Field(default=True)
    order_correct: bool = Field(default=True)
    content_sufficiency_score: float = Field(default=1.0, ge=0.0, le=1.0)
    overall_score: float = Field(default=1.0, ge=0.0, le=1.0)

    model_config = {"frozen": True}

    def get_critical_issues(self) -> Tuple[ContentIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "critical")


class AIDimension(BaseModel):
    """AI 分析的单个维度评估."""

    name: str = Field(description="维度名称")
    score: float = Field(default=0.0, ge=0.0, le=10.0, description="评分 (0-10)")
    comment: str = Field(default="", description="评价")
    suggestions: Tuple[str, ...] = Field(
        default_factory=tuple, description="改进建议"
    )

    model_config = {"frozen": True}


class AIReport(BaseModel):
    """AI 内容分析报告."""

    available: bool = Field(default=False, description="AI分析是否可用")
    error_message: str = Field(default="", description="错误信息（如有）")
    dimensions: Tuple[AIDimension, ...] = Field(
        default_factory=tuple, description="各维度评估"
    )
    overall_score: float = Field(default=0.0, ge=0.0, le=10.0, description="综合评分")
    summary: str = Field(default="", description="总体评价")
    risk_warnings: Tuple[str, ...] = Field(
        default_factory=tuple, description="风险提示"
    )

    model_config = {"frozen": True}


class MeetingQuestion(BaseModel):
    """经营分析会提问建议的单条问题."""

    category: str = Field(description="问题类别: 精准追问|战略质询|风险预警")
    question: str = Field(description="具体问题文本")
    rationale: str = Field(description="为什么问这个问题（基于材料的哪个发现）")
    target_section: str = Field(default="", description="针对文档的哪个章节/内容")
    difficulty: str = Field(default="basic", description="难度: basic|advanced|expert")

    model_config = {"frozen": True}


class MeetingQuestionsResult(BaseModel):
    """经营分析会提问建议结果."""

    available: bool = Field(default=False, description="是否生成成功")
    error_message: str = Field(default="", description="错误信息")
    questions: Tuple[MeetingQuestion, ...] = Field(
        default_factory=tuple, description="提问建议列表"
    )
    opening_remark: str = Field(default="", description="开场白建议")

    model_config = {"frozen": True}


class ReviewReport(BaseModel):
    """综合审核报告."""

    filename: str = Field(default="", description="审核文件名")
    department: str = Field(default="", description="事业部名称")
    review_timestamp: str = Field(default="", description="审核时间")

    format_report: FormatReport = Field(default_factory=FormatReport)
    content_report: ContentReport = Field(default_factory=ContentReport)
    ai_report: AIReport = Field(default_factory=AIReport)

    overall_score: float = Field(default=0.0, ge=0.0, le=100.0, description="综合评分")
    status: str = Field(default="pending", description="整体状态")
    summary: str = Field(default="", description="审核摘要")

    model_config = {"frozen": False}

    def to_dict(self) -> dict:
        return self.model_dump()

    def to_json(self) -> str:
        import json
        return json.dumps(self.model_dump(), ensure_ascii=False, indent=2)
