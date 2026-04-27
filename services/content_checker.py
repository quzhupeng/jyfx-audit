"""内容检查器 — 章节缺失/顺序/内容厚度."""

from __future__ import annotations

from typing import List, Optional, Set

from models.document import ParsedDocument
from models.review import ContentIssue, ContentReport
from models.template import (
    ChapterMatch,
    ContentRule,
    SectionDefinition,
    SectionMap,
    Template,
)


def _check_section_content(
    doc: ParsedDocument,
    match: ChapterMatch,
    section: SectionDefinition,
) -> List[ContentIssue]:
    """检查单个章节的内容充分性.

    内容检查基于内容深度（文字量、数据、要素），而非页数。

    Args:
        doc: 文档
        match: 章节匹配结果
        section: 章节定义

    Returns:
        内容问题列表
    """
    issues: List[ContentIssue] = []
    rules = section.content_rules

    # 收集章节文本
    section_text = ""
    for pn in range(match.page_start, match.page_end + 1):
        section_text += doc.get_page_text(pn) + "\n"

    # 1. 页数仅供参考（不硬性要求）
    actual_pages = match.page_end - match.page_start + 1
    if actual_pages < rules.min_pages:
        issues.append(
            ContentIssue(
                type="insufficient_content",
                severity="info",
                section_id=section.id,
                section_name=section.name,
                message=(
                    f"章节'{section.name}'页数参考值：实际{actual_pages}页，"
                    f"建议{rules.min_pages}页（仅供参考，不影响评分）"
                ),
                detail={
                    "actual_pages": actual_pages,
                    "suggested_pages": rules.min_pages,
                },
            )
        )

    # 2. 检查整章节文字长度（核心指标）
    text_len = len(section_text.replace("\n", "").replace(" ", ""))
    min_length = rules.min_text_length_section or rules.min_text_length
    if text_len < min_length:
        issues.append(
            ContentIssue(
                type="insufficient_content",
                severity="warning",
                section_id=section.id,
                section_name=section.name,
                message=f"章节'{section.name}'文字内容过少（实际{text_len}字，要求至少{min_length}字）",
                detail={
                    "actual_length": text_len,
                    "required_length": min_length,
                },
            )
        )

    # 3. 检查必需元素
    section_text_normalized = section_text.lower()
    for element in rules.required_elements:
        if element.lower() not in section_text_normalized:
            issues.append(
                ContentIssue(
                    type="missing_element",
                    severity="warning",
                    section_id=section.id,
                    section_name=section.name,
                    message=f"章节'{section.name}'缺少必要元素：'{element}'",
                    detail={"missing_element": element},
                )
            )

    # 4. 检查是否包含数据（数字）
    if rules.requires_data:
        has_numbers = any(c.isdigit() for c in section_text)
        if not has_numbers:
            issues.append(
                ContentIssue(
                    type="missing_element",
                    severity="warning",
                    section_id=section.id,
                    section_name=section.name,
                    message=f"章节'{section.name}'要求包含数据，但未检测到数值内容",
                    detail={"required": "数据/数字"},
                )
            )

    # 5. 检查内容深度（如有定义 depth_indicators）
    if rules.depth_indicators:
        found_depth = False
        for indicator in rules.depth_indicators:
            if indicator.lower() in section_text_normalized:
                found_depth = True
                break
        if not found_depth and text_len >= min_length:
            issues.append(
                ContentIssue(
                    type="insufficient_content",
                    severity="info",
                    section_id=section.id,
                    section_name=section.name,
                    message=(
                        f"章节'{section.name}'建议包含更深层的分析内容"
                        f"（如：{', '.join(rules.depth_indicators[:3])}等）"
                    ),
                    detail={"depth_indicators": list(rules.depth_indicators)},
                )
            )

    return issues


class ContentChecker:
    """内容检查器."""

    def __init__(self, template: Template):
        self.template = template

    def check(
        self, doc: ParsedDocument, section_map: SectionMap
    ) -> ContentReport:
        """对文档执行内容完整性检查.

        Args:
            doc: 解析后的文档
            section_map: 章节映射结果

        Returns:
            ContentReport
        """
        issues: List[ContentIssue] = []

        # 1. 检查核心章节缺失
        for missing_id in section_map.missing_essential:
            sec = next(
                (s for s in self.template.sections if s.id == missing_id), None
            )
            sec_name = sec.name if sec else missing_id
            issues.append(
                ContentIssue(
                    type="missing_section",
                    severity="critical",
                    section_id=missing_id,
                    section_name=sec_name,
                    message=f"缺失核心章节：'{sec_name}'——此章节为经营分析会汇报必填内容",
                    detail={"essential": True},
                )
            )

        # 2. 检查非核心章节缺失
        for section in self.template.optional_sections:
            matched = any(
                ch.matched and ch.section_id == section.id
                for ch in section_map.sections
            )
            if not matched:
                issues.append(
                    ContentIssue(
                        type="missing_section",
                        severity="info",
                        section_id=section.id,
                        section_name=section.name,
                        message=f"未检测到可选章节：'{section.name}'",
                        detail={"essential": False},
                    )
                )

        # 3. 检查章节顺序
        if not section_map.is_sequential:
            for order_issue in section_map.order_issues:
                issues.append(
                    ContentIssue(
                        type="order_error",
                        severity="warning",
                        message=order_issue,
                        detail={},
                    )
                )

        # 4. 检查每个已匹配章节的内容充分性
        for match in section_map.sections:
            if not match.matched:
                continue
            section_def = next(
                (s for s in self.template.sections if s.id == match.section_id),
                None,
            )
            if section_def:
                section_issues = _check_section_content(doc, match, section_def)
                issues.extend(section_issues)

        # 计算评分
        # 区分 info 级别（仅供参考）和 warning/critical 级别（影响评分）
        serious_issues = [i for i in issues if i.severity in ("warning", "critical", "error")]
        info_issues = [i for i in issues if i.severity == "info"]

        total_sections = self.template.sections
        total_checks = len(total_sections) * 3
        if total_checks == 0:
            total_checks = 1

        # 只用 serious issues 扣分，info 不扣分
        content_score = max(1.0 - len(serious_issues) / total_checks, 0.0)
        essential_complete = len(section_map.missing_essential) == 0

        return ContentReport(
            total_issues=len(issues),
            issues=tuple(issues),
            section_coverage=section_map.coverage_ratio,
            essential_complete=essential_complete,
            order_correct=section_map.is_sequential,
            content_sufficiency_score=round(content_score, 2),
            overall_score=round(
                (section_map.coverage_ratio * 0.5 + content_score * 0.5), 2
            ),
        )
