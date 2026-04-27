"""格式检查器 — 字体/字号/颜色/排版验证."""

from __future__ import annotations

from typing import List, Optional, Tuple

from models.document import Page, ParsedDocument, TextBlock
from models.review import FormatIssue, FormatReport
from models.template import ChapterMatch, FormatRule, SectionMap, Template
from utils.color_utils import (
    format_srgb,
    hex_to_rgb,
    is_color_within_tolerance,
    normalize_color_name,
    srgb_to_rgb,
)


def _font_matches_allowed(font_name: str, allowed_fonts: Tuple[str, ...]) -> bool:
    """检查字体是否在允许列表中（模糊匹配）."""
    if not allowed_fonts:
        return True  # 无限制
    normalized = normalize_color_name(font_name)
    return any(
        normalize_color_name(allowed) in normalized
        or normalized in normalize_color_name(allowed)
        for allowed in allowed_fonts
    )


def _color_matches_allowed(
    color: int, allowed_colors: Tuple[str, ...], tolerance: int
) -> bool:
    """检查颜色是否在允许列表中."""
    if not allowed_colors:
        return True  # 无限制
    return any(
        is_color_within_tolerance(color, hex_color, tolerance)
        for hex_color in allowed_colors
    )


def check_page_format(
    page: Page,
    format_rule: FormatRule,
    chapter: Optional[ChapterMatch] = None,
) -> List[FormatIssue]:
    """检查单页的格式问题.

    Args:
        page: 页面对象
        format_rule: 格式规则
        chapter: 所属章节信息（可选，用于报告定位）

    Returns:
        格式问题列表
    """
    issues: List[FormatIssue] = []

    for block in page.blocks:
        if block.block_type == 1:  # 跳过图片块
            continue

        for span in block.spans:
            if not span.text.strip():
                continue

            # 1. 字体检查
            if not _font_matches_allowed(span.font, format_rule.allowed_fonts):
                issues.append(
                    FormatIssue(
                        page_number=page.page_number,
                        category="font",
                        severity="warning",
                        message=f"字体 '{span.font}' 不在允许列表中",
                        detail={
                            "actual_font": span.font,
                            "allowed_fonts": list(format_rule.allowed_fonts),
                            "size": span.size,
                        },
                        text_snippet=span.text[:50],
                    )
                )

            # 2. 字号检查
            if span.size > 0:
                size_range = format_rule.font_size_range
                if span.size < size_range[0] or span.size > size_range[1]:
                    # 判断是标题还是正文
                    if span.size >= 22:
                        title_range = format_rule.title_size_range
                        if span.size < title_range[0] or span.size > title_range[1]:
                            issues.append(
                                FormatIssue(
                                    page_number=page.page_number,
                                    category="size",
                                    severity="warning",
                                    message=f"标题字号 {span.size}pt 超出范围 [{title_range[0]}-{title_range[1]}]",
                                    detail={
                                        "actual_size": span.size,
                                        "expected_range": list(title_range),
                                        "text_type": "标题",
                                    },
                                    text_snippet=span.text[:50],
                                )
                            )
                    else:
                        body_range = format_rule.body_size_range
                        if span.size < body_range[0] or span.size > body_range[1]:
                            issues.append(
                                FormatIssue(
                                    page_number=page.page_number,
                                    category="size",
                                    severity="info",
                                    message=f"正文字号 {span.size}pt 超出范围 [{body_range[0]}-{body_range[1]}]",
                                    detail={
                                        "actual_size": span.size,
                                        "expected_range": list(body_range),
                                        "text_type": "正文",
                                    },
                                    text_snippet=span.text[:50],
                                )
                            )

            # 3. 颜色检查
            if span.color > 0 and not _color_matches_allowed(
                span.color, format_rule.allowed_colors, format_rule.color_tolerance
            ):
                issues.append(
                    FormatIssue(
                        page_number=page.page_number,
                        category="color",
                        severity="info",
                        message=f"颜色 {format_srgb(span.color)} 不在允许的配色方案中",
                        detail={
                            "actual_color": format_srgb(span.color),
                            "allowed_colors": list(format_rule.allowed_colors),
                            "tolerance": format_rule.color_tolerance,
                        },
                        text_snippet=span.text[:50],
                    )
                )

            # 4. 标题位置检查（大号文字应在页面上方）
            if span.size >= 22 and page.height > 0:
                y_ratio = span.origin[1] / page.height
                if y_ratio > format_rule.title_top_ratio:
                    issues.append(
                        FormatIssue(
                            page_number=page.page_number,
                            category="layout",
                            severity="warning",
                            message=f"大号文字({span.size}pt)不在页面顶部区域",
                            detail={
                                "y_position_ratio": round(y_ratio, 2),
                                "expected_max_ratio": format_rule.title_top_ratio,
                            },
                            text_snippet=span.text[:50],
                        )
                    )

            # 5. 页边距检查
            x0, y0, x1, y1 = span.bbox
            margin = format_rule.margin_threshold
            if x0 < margin or y0 < margin:
                issues.append(
                    FormatIssue(
                        page_number=page.page_number,
                        category="margin",
                        severity="info",
                        message=f"文字过于靠近页边（距边缘 {min(x0, y0):.0f}pt）",
                        detail={
                            "position": (round(x0), round(y0)),
                            "margin_threshold": margin,
                        },
                        text_snippet=span.text[:50],
                    )
                )

    return issues


class FormatChecker:
    """格式检查器."""

    def __init__(self, template: Template):
        self.template = template

    def check(
        self, doc: ParsedDocument, section_map: Optional[SectionMap] = None
    ) -> FormatReport:
        """对文档执行完整格式检查.

        Args:
            doc: 解析后的文档
            section_map: 章节映射（可选，有则按章节规则检查，无则用全局规则）

        Returns:
            FormatReport
        """
        all_issues: List[FormatIssue] = []

        # 构建页面到章节的映射
        page_chapter_map = {}
        if section_map:
            for ch in section_map.sections:
                if ch.matched:
                    for pn in range(ch.page_start, ch.page_end + 1):
                        # 找到该章节的定义
                        for sec in self.template.sections:
                            if sec.id == ch.section_id:
                                page_chapter_map.setdefault(pn, (sec, ch))
                                break

        for page in doc.pages:
            chapter_info = page_chapter_map.get(page.page_number)
            if chapter_info:
                section_def, ch_match = chapter_info
                format_rule = section_def.format
            else:
                # 使用默认格式规则
                format_rule = FormatRule()

            issues = check_page_format(page, format_rule)
            all_issues.extend(issues)

        # 计算各维度评分
        total_spans = sum(
            len([s for b in p.blocks if b.block_type == 0 for s in b.spans])
            for p in doc.pages
        )
        if total_spans == 0:
            return FormatReport(
                total_issues=0,
                overall_score=1.0,
            )

        font_issues = len([i for i in all_issues if i.category == "font"])
        size_issues = len([i for i in all_issues if i.category == "size"])
        color_issues = len([i for i in all_issues if i.category == "color"])
        layout_issues = len([i for i in all_issues if i.category in ("layout", "margin")])

        font_score = max(1.0 - font_issues / total_spans, 0.0)
        size_score = max(1.0 - size_issues / total_spans, 0.0)
        color_score = max(1.0 - color_issues / total_spans, 0.0)
        layout_score = max(1.0 - layout_issues / total_spans, 0.0)

        overall = (font_score * 0.3 + size_score * 0.3 + color_score * 0.2 + layout_score * 0.2)

        return FormatReport(
            total_issues=len(all_issues),
            issues=tuple(all_issues),
            font_score=round(font_score, 2),
            size_score=round(size_score, 2),
            color_score=round(color_score, 2),
            layout_score=round(layout_score, 2),
            overall_score=round(overall, 2),
        )
