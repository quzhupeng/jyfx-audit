"""Template, SectionDefinition, FormatRule, ContentRule — 模板系统数据模型."""

from __future__ import annotations

from typing import Optional, Tuple

from pydantic import BaseModel, Field


class DetectionRule(BaseModel):
    """章节检测规则."""

    keywords: Tuple[str, ...] = Field(description="检测关键字列表")
    match_mode: str = Field(default="any", description="匹配模式: any | all")
    search_scope: str = Field(
        default="first_page",
        description="搜索范围: first_page | first_3_pages | full",
    )
    weight: float = Field(default=1.0, ge=0.0, le=2.0, description="关键字权重")

    model_config = {"frozen": True}


class FormatRule(BaseModel):
    """格式规则."""

    allowed_fonts: Tuple[str, ...] = Field(
        default_factory=tuple, description="允许的字体名称列表"
    )
    font_size_range: Tuple[float, float] = Field(
        default=(10, 48), description="字号范围 (min, max) pts"
    )
    title_size_range: Tuple[float, float] = Field(
        default=(22, 48), description="标题字号范围 pts"
    )
    body_size_range: Tuple[float, float] = Field(
        default=(10, 28), description="正文字号范围 pts"
    )
    allowed_colors: Tuple[str, ...] = Field(
        default_factory=tuple,
        description="允许的配色，十六进制颜色值如 '#333333'",
    )
    color_tolerance: int = Field(default=30, description="颜色通道容差 (0-255)")
    title_top_ratio: float = Field(
        default=0.15, description="标题应在页面上方此比例内"
    )
    margin_threshold: float = Field(
        default=20.0, description="页边距最小阈值 (pts)"
    )

    model_config = {"frozen": True}


class ContentRule(BaseModel):
    """内容规则."""

    min_pages: int = Field(default=1, description="建议最少页数（仅作参考，不硬性要求）")
    required_elements: Tuple[str, ...] = Field(
        default_factory=tuple, description="必须包含的元素描述"
    )
    requires_data: bool = Field(default=False, description="是否要求包含数据")
    requires_chart: bool = Field(default=False, description="是否要求包含图表")
    min_text_length: int = Field(
        default=50, description="单页最少文字长度（字符）"
    )
    min_text_length_section: int = Field(
        default=100, description="整章节最少文字长度（跨多页累加）"
    )
    depth_indicators: Tuple[str, ...] = Field(
        default_factory=tuple,
        description="深度指标关键字（如'深层原因'、'改进路径'等），用于检测分析是否到位",
    )

    model_config = {"frozen": True}


class SectionDefinition(BaseModel):
    """单个章节的定义."""

    id: str = Field(description="章节唯一标识，如 'cover', 'business_overview'")
    name: str = Field(description="章节显示名称，如 '经营概况'")
    order: int = Field(description="章节在模板中的顺序 (从0开始)")
    essential: bool = Field(default=True, description="是否为核心章节，缺失时严重告警")
    detection: DetectionRule = Field(description="检测规则")
    format: FormatRule = Field(default_factory=FormatRule)
    content_rules: ContentRule = Field(default_factory=ContentRule)
    description: str = Field(default="", description="章节说明")

    model_config = {"frozen": True}


class SegmentInfo(BaseModel):
    """检测到的文档内容段信息."""

    start_page: int = Field(description="起始页码 (1-indexed)")
    end_page: int = Field(description="结束页码 (1-indexed)")
    title_text: str = Field(default="", description="检测到的章节标题文本")
    title_page: int = Field(default=0, description="标题所在页码")
    text_length: int = Field(default=0, description="段内文字总长度")
    page_count: int = Field(default=0, description="段内页数")

    model_config = {"frozen": True}


class ChapterMatch(BaseModel):
    """章节匹配结果."""

    section_id: str = Field(description="匹配到的章节ID")
    section_name: str = Field(description="章节名称")
    page_start: int = Field(default=0, description="起始页码")
    page_end: int = Field(default=0, description="结束页码")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="匹配置信度")
    matched_keywords: Tuple[str, ...] = Field(
        default_factory=tuple, description="命中的关键字"
    )
    total_keywords: int = Field(default=0, description="模板定义的总关键字数")
    matched: bool = Field(default=False, description="是否成功匹配")
    segment_info: Optional[SegmentInfo] = Field(
        default=None, description="检测到的内容段信息（柔性匹配时使用）"
    )

    model_config = {"frozen": True}


class SectionMap(BaseModel):
    """模板匹配后的章节映射."""

    sections: Tuple[ChapterMatch, ...] = Field(
        default_factory=tuple, description="章节匹配列表"
    )
    matched_count: int = Field(default=0, description="成功匹配的章节数")
    total_count: int = Field(default=0, description="模板定义的章节总数")
    is_sequential: bool = Field(default=True, description="章节顺序是否正确")
    missing_essential: Tuple[str, ...] = Field(
        default_factory=tuple, description="缺失的核心章节ID列表"
    )
    order_issues: Tuple[str, ...] = Field(
        default_factory=tuple, description="顺序问题描述"
    )

    model_config = {"frozen": True}

    @property
    def coverage_ratio(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.matched_count / self.total_count


class Template(BaseModel):
    """完整的审核模板."""

    name: str = Field(default="默认模板", description="模板名称")
    version: str = Field(default="1.0", description="模板版本")
    sections: Tuple[SectionDefinition, ...] = Field(
        default_factory=tuple, description="章节定义列表"
    )
    metadata: dict = Field(default_factory=dict, description="模板元信息")

    model_config = {"frozen": True}

    @property
    def essential_sections(self) -> Tuple[SectionDefinition, ...]:
        return tuple(s for s in self.sections if s.essential)

    @property
    def optional_sections(self) -> Tuple[SectionDefinition, ...]:
        return tuple(s for s in self.sections if not s.essential)
