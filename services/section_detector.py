"""章节边界检测器 — 通过标题检测找到章节边界，柔性匹配模板章节.

核心算法：
1. 逐页扫描，检测"章节标题候选"（大字号 + 页面上方区域 + 模板关键字匹配）
2. 合并连续的同章节边界（如标杆案例跨多页）
3. 相邻边界之间的页面 → 一个内容段（Segment）
4. 两轮分类：先匹配有标题的段（高置信度），再匹配无标题的前置段
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from models.document import Page, ParsedDocument, Span
from models.template import (
    ChapterMatch,
    DetectionRule,
    SectionDefinition,
    SectionMap,
    SegmentInfo,
    Template,
)


def _normalize(text: str) -> str:
    """规范化文本用于比较."""
    return text.lower().replace(" ", "").replace("\n", "").replace("\r", "")


def _extract_title_candidates(
    page: Page, min_size: float = 22.0, top_ratio: float = 0.3
) -> List[str]:
    """从页面中提取标题候选文本.

    条件：
    - 字号 >= min_size
    - 位于页面上方 top_ratio 比例内

    Returns:
        标题文本列表
    """
    if page.height == 0:
        return []

    candidates: List[str] = []
    for block in page.blocks:
        if block.block_type != 0:
            continue
        for span in block.spans:
            text = span.text.strip()
            if not text or span.size < min_size:
                continue
            # 检查是否在页面上方区域
            y_ratio = span.origin[1] / page.height
            if y_ratio <= top_ratio:
                candidates.append(text)

    return candidates


def _keyword_match_score(
    text: str, keywords: Tuple[str, ...], match_mode: str
) -> Tuple[float, Set[str]]:
    """计算文本与关键字的匹配分数.

    Returns:
        (score, matched_keywords)
    """
    if not keywords:
        return 0.0, set()

    normalized_text = _normalize(text)
    hits: Set[str] = set()

    for kw in keywords:
        if _normalize(kw) in normalized_text:
            hits.add(kw)

    if match_mode == "all":
        score = len(hits) / len(keywords) if keywords else 0.0
    else:
        # any 模式：命中越多分越高
        score = len(hits) / len(keywords) if keywords else 0.0

    return score, hits


def _get_matching_section_ids(
    title: str, template: Template
) -> Set[str]:
    """获取标题匹配到的模板章节ID集合."""
    normalized = _normalize(title)
    matched_ids: Set[str] = set()
    for section in template.sections:
        for kw in section.detection.keywords:
            if _normalize(kw) in normalized:
                matched_ids.add(section.id)
                break
    return matched_ids


def _classify_segment_to_chapter(
    segment_text: str,
    segment_title: str,
    template: Template,
    used_section_ids: Set[str],
) -> Tuple[Optional[SectionDefinition], float, Set[str]]:
    """将内容段归类到最匹配的模板章节.

    Args:
        segment_text: 段内全部文本
        segment_title: 段的标题文本
        template: 模板
        used_section_ids: 已分配的章节ID集合

    Returns:
        (best_section, confidence, matched_keywords)
    """
    best_section: Optional[SectionDefinition] = None
    best_score = 0.0
    best_hits: Set[str] = set()

    for section in template.sections:
        if section.id in used_section_ids:
            continue

        detection = section.detection

        # 综合标题匹配和内容匹配
        title_score, title_hits = _keyword_match_score(
            segment_title, detection.keywords, detection.match_mode
        )
        content_score, content_hits = _keyword_match_score(
            segment_text, detection.keywords, detection.match_mode
        )

        # 标题匹配权重更高
        combined_score = title_score * 0.7 + content_score * 0.3
        combined_hits = title_hits | content_hits

        # 乘以权重
        final_score = combined_score * detection.weight

        if final_score > best_score:
            best_score = final_score
            best_section = section
            best_hits = combined_hits

    # 有标题的段阈值较低(0.05)，无标题的段阈值较高(0.15)
    min_threshold = 0.05 if segment_title.strip() else 0.15
    if best_section is None or best_score < min_threshold:
        return None, 0.0, set()

    # 置信度归一化到 0-1
    confidence = min(best_score, 1.0)
    return best_section, confidence, best_hits


class SectionDetector:
    """章节边界检测器."""

    def __init__(self, template: Template):
        self.template = template

        # 收集所有模板关键字
        self._all_keywords: Set[str] = set()
        for section in template.sections:
            for kw in section.detection.keywords:
                self._all_keywords.add(_normalize(kw))

    def detect_boundaries(
        self, doc: ParsedDocument, min_size: float = 22.0, top_ratio: float = 0.3
    ) -> List[Tuple[int, str]]:
        """检测文档中的章节边界.

        扫描每一页，查找包含模板关键字的标题级文字。

        Args:
            doc: 解析后的文档
            min_size: 最小标题字号
            top_ratio: 标题应在页面上方此比例内

        Returns:
            [(页码, 标题文本), ...] 列表，按页码排序
        """
        boundaries: List[Tuple[int, str]] = []

        for page in doc.pages:
            titles = _extract_title_candidates(page, min_size, top_ratio)

            for title_text in titles:
                # 检查是否匹配任一模板关键字
                normalized_title = _normalize(title_text)
                for section in self.template.sections:
                    for kw in section.detection.keywords:
                        if _normalize(kw) in normalized_title:
                            boundaries.append((page.page_number, title_text))
                            break
                    else:
                        continue
                    break  # 每页只取第一个匹配的标题

        # 去重：同一页只保留第一个
        seen_pages: Set[int] = set()
        unique: List[Tuple[int, str]] = []
        for page_num, title in boundaries:
            if page_num not in seen_pages:
                seen_pages.add(page_num)
                unique.append((page_num, title))

        return unique

    def _merge_consecutive_same_section(
        self, boundaries: List[Tuple[int, str]]
    ) -> List[Tuple[int, str]]:
        """合并连续的同章节边界.

        当连续多页有标题且这些标题匹配同一组模板章节时，
        只保留第一个标题作为边界，后续页面归入同一内容段。

        例如：Pages 18-21 都是"标杆案例"相关标题，合并为一个边界。
        """
        if len(boundaries) <= 1:
            return boundaries

        merged: List[Tuple[int, str]] = [boundaries[0]]
        # 跟踪最后一个被合并进来的页码（而非边界页）
        last_merged_page = boundaries[0][0]

        for i in range(1, len(boundaries)):
            curr_page, curr_title = boundaries[i]

            # 检查是否与上一个合并边界连续
            if curr_page == last_merged_page + 1:
                prev_title = merged[-1][1]
                prev_ids = _get_matching_section_ids(prev_title, self.template)
                curr_ids = _get_matching_section_ids(curr_title, self.template)

                # 如果匹配到的章节集合相同且非空，合并
                if prev_ids and prev_ids == curr_ids:
                    last_merged_page = curr_page  # 扩展合并范围
                    continue  # 跳过此边界，归入前一段

            merged.append(boundaries[i])
            last_merged_page = curr_page

        return merged

    def build_segments(
        self,
        doc: ParsedDocument,
        boundaries: List[Tuple[int, str]],
    ) -> List[SegmentInfo]:
        """根据边界将文档拆分为内容段.

        Args:
            doc: 解析后的文档
            boundaries: detect_boundaries 的输出

        Returns:
            SegmentInfo 列表
        """
        if not boundaries:
            # 无边界 → 整个文档作为一个段
            total_text = doc.all_text.replace("\n", "").replace(" ", "")
            return [
                SegmentInfo(
                    start_page=1,
                    end_page=doc.page_count,
                    title_text="",
                    title_page=0,
                    text_length=len(total_text),
                    page_count=doc.page_count,
                )
            ]

        segments: List[SegmentInfo] = []
        total_pages = doc.page_count

        for i, (page_num, title_text) in enumerate(boundaries):
            start_page = page_num

            # 段的结束页 = 下一边界的前一页，或文档末尾
            if i + 1 < len(boundaries):
                end_page = boundaries[i + 1][0] - 1
            else:
                end_page = total_pages

            # 计算段内文本长度
            text_len = 0
            for pn in range(start_page, end_page + 1):
                page_text = doc.get_page_text(pn)
                text_len += len(page_text.replace("\n", "").replace(" ", ""))

            segments.append(
                SegmentInfo(
                    start_page=start_page,
                    end_page=end_page,
                    title_text=title_text,
                    title_page=page_num,
                    text_length=text_len,
                    page_count=end_page - start_page + 1,
                )
            )

        # 如果第一个边界不在第1页，前面的内容作为"前置段"
        if boundaries[0][0] > 1:
            first_boundary_page = boundaries[0][0]
            text_len = 0
            for pn in range(1, first_boundary_page):
                page_text = doc.get_page_text(pn)
                text_len += len(page_text.replace("\n", "").replace(" ", ""))

            pre_segment = SegmentInfo(
                start_page=1,
                end_page=first_boundary_page - 1,
                title_text="",
                title_page=0,
                text_length=text_len,
                page_count=first_boundary_page - 1,
            )
            segments.insert(0, pre_segment)

        return segments

    def match_segments_to_chapters(
        self, doc: ParsedDocument, segments: List[SegmentInfo]
    ) -> List[ChapterMatch]:
        """将内容段匹配到模板章节 — 两轮分类.

        第一轮：有标题的段优先匹配（高置信度）
        第二轮：无标题的前置段使用剩余章节匹配

        Args:
            doc: 文档
            segments: 内容段列表

        Returns:
            ChapterMatch 列表（与 template.sections 顺序一致）
        """
        used_section_ids: Set[str] = set()
        segment_matches: Dict[int, Tuple[SectionDefinition, float, Set[str]]] = {}

        # 预计算每个段的文本（避免重复遍历）
        segment_texts: Dict[int, str] = {}
        for seg_idx, segment in enumerate(segments):
            seg_text = ""
            for pn in range(segment.start_page, segment.end_page + 1):
                seg_text += doc.get_page_text(pn) + "\n"
            segment_texts[seg_idx] = seg_text

        # 第一轮：有标题的段优先匹配
        for seg_idx, segment in enumerate(segments):
            if not segment.title_text.strip():
                continue  # 跳过无标题的段

            section, confidence, hits = _classify_segment_to_chapter(
                segment_texts[seg_idx], segment.title_text,
                self.template, used_section_ids,
            )
            if section:
                segment_matches[seg_idx] = (section, confidence, hits)
                used_section_ids.add(section.id)

        # 第二轮：无标题的段（前置段）用剩余章节匹配
        for seg_idx, segment in enumerate(segments):
            if seg_idx in segment_matches:
                continue
            if segment.title_text.strip():
                continue  # 第一轮已处理

            section, confidence, hits = _classify_segment_to_chapter(
                segment_texts[seg_idx], segment.title_text,
                self.template, used_section_ids,
            )
            if section:
                segment_matches[seg_idx] = (section, confidence, hits)
                used_section_ids.add(section.id)

        # 构建 ChapterMatch 列表（与模板章节顺序一致）
        chapter_matches: Dict[str, ChapterMatch] = {}

        for seg_idx, (section, confidence, hits) in segment_matches.items():
            segment = segments[seg_idx]
            chapter_matches[section.id] = ChapterMatch(
                section_id=section.id,
                section_name=section.name,
                page_start=segment.start_page,
                page_end=segment.end_page,
                confidence=round(confidence, 3),
                matched_keywords=tuple(sorted(hits)),
                total_keywords=len(section.detection.keywords),
                matched=True,
                segment_info=segment,
            )

        # 为未匹配的章节创建空 match
        for section in self.template.sections:
            if section.id not in chapter_matches:
                chapter_matches[section.id] = ChapterMatch(
                    section_id=section.id,
                    section_name=section.name,
                    page_start=0,
                    page_end=0,
                    confidence=0.0,
                    matched_keywords=(),
                    total_keywords=len(section.detection.keywords),
                    matched=False,
                    segment_info=None,
                )

        # 按模板顺序返回
        result: List[ChapterMatch] = []
        for section in self.template.sections:
            result.append(chapter_matches[section.id])

        return result


def match_all_chapters_flexible(
    doc: ParsedDocument,
    template: Template,
) -> SectionMap:
    """柔性章节匹配 — 基于标题边界检测，不依赖固定页数.

    算法：
    1. 扫描文档每一页，检测标题级文字中的模板关键字
    2. 合并连续的同章节边界
    3. 以边界拆分文档为内容段
    4. 两轮分类匹配到模板章节
    5. 返回 SectionMap

    Args:
        doc: 解析后的文档
        template: 审核模板

    Returns:
        SectionMap 对象
    """
    detector = SectionDetector(template)

    # Step 1: 检测边界
    boundaries = detector.detect_boundaries(doc)

    # Step 2: 合并连续同章节边界
    boundaries = detector._merge_consecutive_same_section(boundaries)

    # Step 3: 构建内容段
    segments = detector.build_segments(doc, boundaries)

    # Step 4: 两轮分类匹配
    chapter_matches = detector.match_segments_to_chapters(doc, segments)

    matched = [c for c in chapter_matches if c.matched]

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
        sections=tuple(chapter_matches),
        matched_count=len(matched),
        total_count=len(template.sections),
        is_sequential=is_sequential,
        missing_essential=missing_essential,
        order_issues=tuple(order_issues),
    )
