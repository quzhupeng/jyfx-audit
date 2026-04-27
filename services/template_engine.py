"""模板引擎 — YAML 模板加载与章节匹配."""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from models.document import Page, ParsedDocument
from models.template import (
    ChapterMatch,
    SectionDefinition,
    SectionMap,
    Template,
)
from config.loader import load_template
from services.section_detector import match_all_chapters_flexible


def _normalize(text: str) -> str:
    """规范化文本用于比较."""
    return text.lower().replace(" ", "").replace("\n", "").replace("\r", "")


def _get_search_text(
    doc: ParsedDocument, section: SectionDefinition
) -> Tuple[str, int, int]:
    """获取搜索范围内的文本.

    Returns:
        (combined_text, start_page, end_page) 页码从1开始
    """
    scope = section.detection.search_scope
    total = doc.page_count

    if scope == "first_page":
        start, end = 1, 1
    elif scope == "first_3_pages":
        start, end = 1, min(3, total)
    else:  # full
        start, end = 1, total

    pages_text = []
    for page_num in range(start, end + 1):
        pages_text.append(doc.get_page_text(page_num))

    return "\n".join(pages_text), start, end


def _keyword_hits(
    text: str, keywords: Tuple[str, ...], match_mode: str
) -> Tuple[Set[str], float]:
    """在文本中搜索关键字命中.

    Returns:
        (命中的关键字集合, 命中率)
    """
    normalized_text = _normalize(text)
    hits: Set[str] = set()

    for kw in keywords:
        normalized_kw = _normalize(kw)
        if normalized_kw in normalized_text:
            hits.add(kw)

    total = len(keywords)
    if total == 0:
        return set(), 0.0

    coverage = len(hits) / total  # 去重命中率

    # 密度分：命中次数 / 关键字总数 (粗略)
    hit_count = sum(
        1 for kw in keywords
        if _normalize(kw) in normalized_text
    )
    density = min(hit_count / (total * 2), 1.0)  # 归一化

    score = coverage * 0.7 + density * 0.3
    return hits, score


def match_chapter(
    doc: ParsedDocument,
    section: SectionDefinition,
    search_start_page: int = 1,
) -> ChapterMatch:
    """在文档中匹配单个章节.

    Args:
        doc: 解析后的文档
        section: 章节定义
        search_start_page: 从哪一页开始搜索 (用于顺序匹配)

    Returns:
        ChapterMatch 对象
    """
    detection = section.detection
    scope = detection.search_scope

    # 确定搜索页码范围
    if scope == "first_page":
        search_pages = range(search_start_page, min(search_start_page + 1, doc.page_count + 1))
    elif scope == "first_3_pages":
        search_pages = range(search_start_page, min(search_start_page + 3, doc.page_count + 1))
    else:
        search_pages = range(search_start_page, doc.page_count + 1)

    # 滑动窗口：逐页扩展搜索范围
    best_hits: Set[str] = set()
    best_score = 0.0
    best_end_page = search_start_page
    matched = False

    accumulated_text = ""
    for page_num in search_pages:
        accumulated_text += doc.get_page_text(page_num) + "\n"

        if detection.match_mode == "any":
            # 任一关键字命中即可
            hits, score = _keyword_hits(accumulated_text, detection.keywords, "any")
            if len(hits) > 0 and score > best_score:
                best_hits = hits
                best_score = score
                best_end_page = page_num
                matched = True
                # any 模式下找到就停止
                break
        else:
            # all 模式：需要全部关键字
            hits, score = _keyword_hits(accumulated_text, detection.keywords, "all")
            if score > best_score:
                best_hits = hits
                best_score = score
                best_end_page = page_num
                if len(hits) == len(detection.keywords):
                    matched = True
                    break

    # 计算最终置信度
    confidence = (best_score * detection.weight) if matched else 0.0
    confidence = min(confidence, 1.0)

    return ChapterMatch(
        section_id=section.id,
        section_name=section.name,
        page_start=search_start_page if matched else 0,
        page_end=best_end_page if matched else 0,
        confidence=confidence,
        matched_keywords=tuple(best_hits),
        total_keywords=len(detection.keywords),
        matched=matched,
    )


def match_all_chapters(
    doc: ParsedDocument,
    template: Template,
) -> SectionMap:
    """对整个文档执行所有章节匹配.

    按模板定义的章节顺序依次搜索文档，每个章节从前一章结束页+1开始搜索。

    Args:
        doc: 解析后的文档
        template: 审核模板

    Returns:
        SectionMap 对象
    """
    chapters: List[ChapterMatch] = []
    current_page = 1

    for section in template.sections:
        match = match_chapter(doc, section, search_start_page=current_page)
        chapters.append(match)
        if match.matched and match.page_end > current_page:
            current_page = match.page_end + 1

    matched = [c for c in chapters if c.matched]

    # 检查顺序
    is_sequential = True
    order_issues: List[str] = []
    last_page = 0
    for ch in matched:
        if ch.page_start < last_page:
            is_sequential = False
            order_issues.append(
                f"章节'{ch.section_name}'出现在第{ch.page_start}页，"
                f"但上一章节在第{last_page}页之后"
            )
        last_page = ch.page_end

    # 缺失的核心章节
    missing_essential = tuple(
        s.id for s in template.essential_sections
        if s.id not in {c.section_id for c in matched}
    )

    return SectionMap(
        sections=tuple(chapters),
        matched_count=len(matched),
        total_count=len(template.sections),
        is_sequential=is_sequential,
        missing_essential=missing_essential,
        order_issues=tuple(order_issues),
    )


def match_all_chapters_no_sequential(
    doc: ParsedDocument,
    template: Template,
) -> SectionMap:
    """非顺序模式：每个章节独立从首页搜索（用于容错场景）."""
    chapters: List[ChapterMatch] = []
    for section in template.sections:
        match = match_chapter(doc, section, search_start_page=1)
        chapters.append(match)

    matched = [c for c in chapters if c.matched]
    missing_essential = tuple(
        s.id for s in template.essential_sections
        if s.id not in {c.section_id for c in matched}
    )

    return SectionMap(
        sections=tuple(chapters),
        matched_count=len(matched),
        total_count=len(template.sections),
        is_sequential=True,  # 非顺序模式不检查顺序
        missing_essential=missing_essential,
        order_issues=(),
    )
