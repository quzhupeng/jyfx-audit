"""测试模板引擎."""

from __future__ import annotations

import pytest

from services.template_engine import (
    match_chapter,
    match_all_chapters,
    match_all_chapters_no_sequential,
    _normalize,
    _keyword_hits,
)
from models.template import ChapterMatch, SectionMap


class TestKeywordHits:
    def test_single_keyword_match(self):
        hits, score = _keyword_hits("经营概况分析报告", ("经营概况",), "any")
        assert "经营概况" in hits
        assert score > 0

    def test_no_match(self):
        hits, score = _keyword_hits("这是测试文本", ("经营概况",), "any")
        assert len(hits) == 0
        assert score == 0.0

    def test_any_mode_one_hit(self):
        hits, score = _keyword_hits(
            "根因分析报告", ("经营概况", "根因分析", "改善措施"), "any"
        )
        assert "根因分析" in hits
        assert score > 0

    def test_all_mode_partial_hit(self):
        hits, score = _keyword_hits(
            "根因分析报告", ("经营概况", "根因分析"), "all"
        )
        assert len(hits) == 1
        # all 模式不会标记 matched（因为不全）
        assert len(hits) < 2

    def test_all_mode_full_match(self):
        hits, score = _keyword_hits(
            "经营概况与根因分析", ("经营概况", "根因分析"), "all"
        )
        assert len(hits) == 2
        assert score > 0.7

    def test_normalized_keywords(self):
        hits, score = _keyword_hits(
            "达 成 率95%", ("达 成 率",), "any"
        )
        assert "达 成 率" in hits
        assert score > 0


class TestMatchChapter:
    def test_match_cover_on_first_page(self, simple_doc, mock_template):
        cover_section = mock_template.sections[0]  # 封面
        match = match_chapter(simple_doc, cover_section)
        assert match.matched
        assert match.section_id == "cover"
        assert len(match.matched_keywords) > 0

    def test_match_toc_in_first_3_pages(self, simple_doc, mock_template):
        toc_section = mock_template.sections[1]  # 目录
        match = match_chapter(simple_doc, toc_section)
        assert match.matched
        assert match.section_id == "toc"

    def test_match_business_overview(self, simple_doc, mock_template):
        bo_section = mock_template.sections[2]  # 经营概况
        match = match_chapter(simple_doc, bo_section)
        assert match.matched
        assert "达成率" in match.matched_keywords or "经营概况" in match.matched_keywords

    def test_no_match_for_missing_section(self, simple_doc, mock_template):
        rca_section = mock_template.sections[3]  # 根因分析 — not in simple doc
        match = match_chapter(simple_doc, rca_section)
        assert not match.matched
        assert match.confidence == 0.0


class TestMatchAllChapters:
    def test_match_all_sequential(self, simple_doc, mock_template):
        section_map = match_all_chapters(simple_doc, mock_template)
        assert section_map.total_count == 4
        assert section_map.matched_count >= 3  # cover, toc, overview 应该匹配
        assert len(section_map.missing_essential) >= 1  # 根因分析缺失

    def test_match_all_no_sequential(self, simple_doc, mock_template):
        section_map = match_all_chapters_no_sequential(simple_doc, mock_template)
        assert section_map.total_count == 4
        assert section_map.matched_count >= 3

    def test_coverage_ratio(self, simple_doc, mock_template):
        section_map = match_all_chapters(simple_doc, mock_template)
        ratio = section_map.coverage_ratio
        assert 0 <= ratio <= 1.0

    def test_missing_essential(self, simple_doc, mock_template):
        section_map = match_all_chapters(simple_doc, mock_template)
        assert "root_cause_analysis" in section_map.missing_essential

    def test_multi_page_doc(self, multi_page_doc, mock_template):
        section_map = match_all_chapters(multi_page_doc, mock_template)
        assert section_map.matched_count >= 3
