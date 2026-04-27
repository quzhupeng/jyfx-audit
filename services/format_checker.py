"""格式检查器 — 聚合式格式审查，聚焦可操作的问题.

检查逻辑基于参考PDF模板的实际格式要求：
- 标题应为蓝色 (R:0;G:154;B:201 = #009AC9)
- 不允许深色背景+深色字体
- 字号范围 [7pt, 60pt]，超出为异常
- 智能字体检测：字体名可读时检查是否符合微软雅黑要求，不可读时跳过

不检查的内容：
- 颜色白名单（PPT中图表/装饰颜色种类多，白名单导致海量误报）
"""

from __future__ import annotations

import re
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

# 嵌入字体子集名称模式（如 CIDFont+F1, ABCDEF+Ghij 等）
# PDF嵌入子集字体的特征：名称中包含 "+" 号（前缀+原始字体名）
_EMBEDDED_FONT_PATTERN = re.compile(r"^[A-Za-z]{2,}\+[A-Za-z]")

# 标准字体：微软雅黑及其变体（模板唯一要求字体）
_STANDARD_FONT_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"^MicrosoftYaHei",
        r"^Microsoft\s*YaHei",
        r"^微软雅黑",
    ]
]


def _is_readable_font(font_name: str) -> bool:
    """判断字体名是否可读（非嵌入子集名称）.

    嵌入子集名如 CIDFont+F1, ABCDEF+Ghij 等无法还原原始字体名。
    可读名如 MicrosoftYaHei, SimSun, Arial 等。
    """
    if not font_name:
        return False
    # 匹配 "XX+Y" 模式的嵌入子集名
    if _EMBEDDED_FONT_PATTERN.match(font_name):
        return False
    return True


def _is_standard_font(font_name: str) -> bool:
    """判断字体是否为模板要求的微软雅黑."""
    return any(p.match(font_name) for p in _STANDARD_FONT_PATTERNS)


def check_document_fonts(doc: ParsedDocument, allowed_fonts: Tuple[str, ...]) -> List[FormatIssue]:
    """文档级字体检查 — 仅当字体名可读时执行.

    算法：
    1. 采样文档中所有span的字体名
    2. 判断字体名是否可读（非CIDFont+Fx模式）
    3. 如果可读：统计字体使用情况，报告非标准字体
    4. 如果不可读：跳过检查，返回空列表

    Args:
        doc: 解析后的文档
        allowed_fonts: 模板定义的允许字体列表

    Returns:
        格式问题列表
    """
    # 收集所有字体名及其使用次数（按span计数）
    font_counter: Counter = Counter()
    total_spans = 0

    for page in doc.pages:
        for block in page.blocks:
            if block.block_type != 0:
                continue
            for span in block.spans:
                if not span.text.strip() or not span.font:
                    continue
                font_counter[span.font] += 1
                total_spans += 1

    if total_spans == 0:
        return []

    # 判断字体名是否可读
    readable_fonts = {f for f in font_counter if _is_readable_font(f)}
    unreadable_fonts = {f for f in font_counter if not _is_readable_font(f)}

    # 如果大部分字体名不可读，说明PDF嵌入方式使得名称不可用
    readable_span_count = sum(font_counter[f] for f in readable_fonts)
    if readable_span_count < total_spans * 0.5:
        # 超过50%的span使用了不可读字体名，跳过字体检查
        return []

    # 字体名可读，执行检查
    issues: List[FormatIssue] = []

    # 统计非标准字体使用情况
    non_standard_fonts: Counter = Counter()
    for font_name, count in font_counter.items():
        if _is_readable_font(font_name) and not _is_standard_font(font_name):
            non_standard_fonts[font_name] = count

    if not non_standard_fonts:
        return issues

    # 非标准字体span占比
    non_standard_total = sum(non_standard_fonts.values())
    non_standard_ratio = non_standard_total / max(total_spans, 1)

    # 只在非标准字体占比超过10%时报告
    if non_standard_ratio >= 0.10:
        font_details = [
            f"{name}: {count}处"
            for name, count in non_standard_fonts.most_common(5)
        ]
        issues.append(
            FormatIssue(
                page_number=0,  # 文档级问题
                category="font",
                severity="info",
                message=(
                    f"文档中{non_standard_ratio:.0%}的文字未使用微软雅黑"
                    f"，涉及: {', '.join(font_details)}"
                ),
                detail={
                    "non_standard_fonts": dict(non_standard_fonts.most_common(10)),
                    "non_standard_ratio": round(non_standard_ratio, 2),
                    "standard_fonts": {
                        f: c for f, c in font_counter.most_common(10)
                        if _is_readable_font(f) and _is_standard_font(f)
                    },
                },
                text_snippet="; ".join(font_details[:3]),
            )
        )

    return issues


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

        # ---- 字体检查（文档级，智能检测） ----
        allowed_fonts = ()
        for sec in self.template.sections:
            if sec.format.allowed_fonts:
                allowed_fonts = sec.format.allowed_fonts
                break

        font_issues = check_document_fonts(doc, allowed_fonts)
        all_issues.extend(font_issues)

        # 计算评分：格式问题只做参考，不影响核心分数
        # 每个页面最多有3类问题，超过50%的页面有问题才扣分
        page_count = doc.page_count if doc.page_count > 0 else 1
        page_issues = [i for i in all_issues if i.page_number > 0]
        pages_with_issues = len(set(i.page_number for i in page_issues))
        issue_ratio = pages_with_issues / page_count

        overall = max(1.0 - issue_ratio * 0.5, 0.5)  # 最低0.5，格式不致命

        # 统计各维度
        color_issues = len([i for i in all_issues if i.category == "color"])
        size_issues = len([i for i in all_issues if i.category == "size"])
        font_issue_count = len([i for i in all_issues if i.category == "font"])
        layout_issues = len([i for i in all_issues if i.category in ("layout", "margin")])

        color_score = max(1.0 - color_issues / max(page_count, 1), 0.5)
        size_score = max(1.0 - size_issues / max(page_count, 1), 0.5)
        layout_score = max(1.0 - layout_issues / max(page_count, 1), 0.5)

        # 字体评分：无问题满分，有问题0.8
        font_score = 0.8 if font_issue_count > 0 else 1.0

        return FormatReport(
            total_issues=len(all_issues),
            issues=tuple(all_issues),
            font_score=round(font_score, 2),
            size_score=round(size_score, 2),
            color_score=round(color_score, 2),
            layout_score=round(layout_score, 2),
            overall_score=round(overall, 2),
        )
