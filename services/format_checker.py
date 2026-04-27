"""格式检查器 — 聚合式格式审查，聚焦可操作的问题.

检查逻辑基于参考PDF模板的实际格式要求：
- 标题应为蓝色 (R:0;G:154;B:201 = #009AC9)
- 不允许深色背景+深色字体
- 字号范围 [7pt, 60pt]，超出为异常

不检查的内容（原因：PDF嵌入字体名称不可靠）：
- 字体名称白名单（PDF中字体显示为 CIDFont+Fx，无法匹配原名）
- 颜色白名单（PPT中图表/装饰颜色种类多，白名单导致海量误报）
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from models.document import Page, ParsedDocument, Span
from models.review import FormatIssue, FormatReport
from models.template import ChapterMatch, FormatRule, SectionMap, Template
from utils.color_utils import (
    color_distance,
    format_srgb,
    hex_to_rgb,
    is_color_within_tolerance,
    normalize_color_name,
    rgb_to_srgb,
    srgb_to_rgb,
)

# 标题蓝色要求：R:0;G:154;B:201 = #009AC9
REQUIRED_TITLE_BLUE_HEX = "#009AC9"
REQUIRED_TITLE_BLUE_SRGB = rgb_to_srgb(0, 154, 201)
TITLE_BLUE_TOLERANCE = 40  # 每通道容差

# 深色阈值（RGB各通道均低于此值视为深色）
DARK_THRESHOLD = 80


def _is_dark_color(srgb: int) -> bool:
    """判断颜色是否为深色."""
    r, g, b = srgb_to_rgb(srgb)
    return r < DARK_THRESHOLD and g < DARK_THRESHOLD and b < DARK_THRESHOLD


def _is_light_color(srgb: int) -> bool:
    """判断颜色是否为浅色（接近白色）."""
    r, g, b = srgb_to_rgb(srgb)
    return r > 200 and g > 200 and b > 200


def check_page_format(
    page: Page,
    format_rule: FormatRule,
    chapter: Optional[ChapterMatch] = None,
) -> List[FormatIssue]:
    """检查单页的格式问题 — 聚合模式.

    不逐span报issue，而是收集页面级统计，只报告有意义的模式问题。

    Args:
        page: 页面对象
        format_rule: 格式规则
        chapter: 所属章节信息（可选）

    Returns:
        格式问题列表（聚合后，数量有限）
    """
    issues: List[FormatIssue] = []

    # 收集本页所有文字span的统计
    title_spans: List[Span] = []  # ≥22pt 标题级
    body_spans: List[Span] = []  # <22pt 正文级
    extreme_small_spans: List[Span] = []  # <7pt 异常小字
    extreme_large_spans: List[Span] = []  # >60pt 异常大字

    for block in page.blocks:
        if block.block_type != 0:
            continue
        for span in block.spans:
            if not span.text.strip():
                continue

            if span.size >= 22:
                title_spans.append(span)
            elif span.size > 0:
                body_spans.append(span)

            if 0 < span.size < 7:
                extreme_small_spans.append(span)
            if span.size > 60:
                extreme_large_spans.append(span)

    # ---- 检查1: 标题蓝色检查 ----
    # 参考模板要求：PPT大标题都为蓝色字体 (R:0;G:154;B:201)
    if title_spans:
        non_blue_titles = []
        for span in title_spans:
            # 黑色文字跳过（有些PPT用黑色标题也是正常的）
            if span.color == 0:
                continue
            # 检查是否为蓝色
            if not is_color_within_tolerance(
                span.color, REQUIRED_TITLE_BLUE_HEX, TITLE_BLUE_TOLERANCE
            ):
                # 排除白色（表格内的大号文字）和红色（警示文字）
                r, g, b = srgb_to_rgb(span.color)
                if not (r > 200 and g > 200 and b > 200):  # 非白色
                    non_blue_titles.append(span)

        if len(non_blue_titles) >= 2:
            # 聚合：多个非蓝色标题时才报
            examples = [s.text[:20] for s in non_blue_titles[:3]]
            issues.append(
                FormatIssue(
                    page_number=page.page_number,
                    category="color",
                    severity="info",
                    message=(
                        f"第{page.page_number}页有{len(non_blue_titles)}处标题非蓝色"
                        f"（建议标题使用蓝色 R:0;G:154;B:201）"
                    ),
                    detail={
                        "count": len(non_blue_titles),
                        "examples": examples,
                        "expected_color": REQUIRED_TITLE_BLUE_HEX,
                    },
                    text_snippet="; ".join(examples),
                )
            )

    # ---- 检查2: 异常字号 ----
    # 只报告极端情况（<7pt 或 >60pt），正常范围 [7, 60] 不报
    if extreme_small_spans:
        examples = [s.text[:15] for s in extreme_small_spans[:3]]
        issues.append(
            FormatIssue(
                page_number=page.page_number,
                category="size",
                severity="info",
                message=(
                    f"第{page.page_number}页有{len(extreme_small_spans)}处极小字号"
                    f"（<{7}pt），可能影响可读性"
                ),
                detail={
                    "count": len(extreme_small_spans),
                    "min_size": min(s.size for s in extreme_small_spans),
                    "examples": examples,
                },
                text_snippet="; ".join(examples),
            )
        )

    if extreme_large_spans:
        examples = [s.text[:15] for s in extreme_large_spans[:3]]
        issues.append(
            FormatIssue(
                page_number=page.page_number,
                category="size",
                severity="info",
                message=f"第{page.page_number}页有{len(extreme_large_spans)}处异常大字号（>{60}pt）",
                detail={
                    "count": len(extreme_large_spans),
                    "max_size": max(s.size for s in extreme_large_spans),
                    "examples": examples,
                },
                text_snippet="; ".join(examples),
            )
        )

    # ---- 检查3: 深色文字+深色背景风险 ----
    # 参考模板要求：不允许深色背景+深色字体
    # 简化检查：深色文字(非黑非蓝)在页面中出现过多时提醒
    dark_non_standard = []
    for span in body_spans:
        if span.color != 0 and _is_dark_color(span.color):
            # 深色但不是蓝色标题
            if not is_color_within_tolerance(
                span.color, REQUIRED_TITLE_BLUE_HEX, TITLE_BLUE_TOLERANCE
            ):
                dark_non_standard.append(span)

    if len(dark_non_standard) >= 5:
        issues.append(
            FormatIssue(
                page_number=page.page_number,
                category="color",
                severity="info",
                message=(
                    f"第{page.page_number}页有{len(dark_non_standard)}处深色非标准文字"
                    f"，请确认不存在「深色背景+深色字体」问题"
                ),
                detail={
                    "count": len(dark_non_standard),
                    "sample_colors": list(
                        set(format_srgb(s.color) for s in dark_non_standard[:5])
                    ),
                },
                text_snippet="",
            )
        )

    return issues


class FormatChecker:
    """格式检查器 — 聚合模式，产出简洁可操作的报告."""

    def __init__(self, template: Template):
        self.template = template

    def check(
        self, doc: ParsedDocument, section_map: Optional[SectionMap] = None
    ) -> FormatReport:
        """对文档执行格式检查.

        Args:
            doc: 解析后的文档
            section_map: 章节映射（可选）

        Returns:
            FormatReport
        """
        all_issues: List[FormatIssue] = []

        # 构建页面到章节的映射
        page_chapter_map: Dict[int, Tuple] = {}
        if section_map:
            for ch in section_map.sections:
                if ch.matched:
                    for pn in range(ch.page_start, ch.page_end + 1):
                        for sec in self.template.sections:
                            if sec.id == ch.section_id:
                                page_chapter_map.setdefault(pn, (sec, ch))
                                break

        for page in doc.pages:
            chapter_info = page_chapter_map.get(page.page_number)
            if chapter_info:
                section_def, _ = chapter_info
                format_rule = section_def.format
            else:
                format_rule = FormatRule()

            issues = check_page_format(page, format_rule)
            all_issues.extend(issues)

        # 计算评分：格式问题只做参考，不影响核心分数
        # 每个页面最多有3类问题，超过50%的页面有问题才扣分
        page_count = doc.page_count if doc.page_count > 0 else 1
        pages_with_issues = len(set(i.page_number for i in all_issues))
        issue_ratio = pages_with_issues / page_count

        overall = max(1.0 - issue_ratio * 0.5, 0.5)  # 最低0.5，格式不致命

        # 统计各维度
        color_issues = len([i for i in all_issues if i.category == "color"])
        size_issues = len([i for i in all_issues if i.category == "size"])
        layout_issues = len([i for i in all_issues if i.category in ("layout", "margin")])

        color_score = max(1.0 - color_issues / max(page_count, 1), 0.5)
        size_score = max(1.0 - size_issues / max(page_count, 1), 0.5)
        layout_score = max(1.0 - layout_issues / max(page_count, 1), 0.5)

        return FormatReport(
            total_issues=len(all_issues),
            issues=tuple(all_issues),
            font_score=1.0,  # 不检查字体名，默认满分
            size_score=round(size_score, 2),
            color_score=round(color_score, 2),
            layout_score=round(layout_score, 2),
            overall_score=round(overall, 2),
        )
