"""测试内容检查器."""

from __future__ import annotations

import pytest

from services.content_checker import ContentChecker
from services.template_engine import match_all_chapters
from models.review import ContentReport, ContentIssue


class TestContentChecker:
    def test_check_returns_report(self, simple_doc, mock_template):
        section_map = match_all_chapters(simple_doc, mock_template)
        checker = ContentChecker(mock_template)
        report = checker.check(simple_doc, section_map)
        assert isinstance(report, ContentReport)
        assert 0 <= report.overall_score <= 1.0

    def test_missing_essential_detected(self, simple_doc, mock_template):
        section_map = match_all_chapters(simple_doc, mock_template)
        checker = ContentChecker(mock_template)
        report = checker.check(simple_doc, section_map)
        # 根因分析缺失应被检测
        critical_issues = report.get_critical_issues()
        assert len(critical_issues) > 0
        assert any("根因分析" in i.message for i in critical_issues)

    def test_essential_complete_false_when_missing(self, simple_doc, mock_template):
        section_map = match_all_chapters(simple_doc, mock_template)
        checker = ContentChecker(mock_template)
        report = checker.check(simple_doc, section_map)
        assert not report.essential_complete

    def test_section_coverage_reported(self, simple_doc, mock_template):
        section_map = match_all_chapters(simple_doc, mock_template)
        checker = ContentChecker(mock_template)
        report = checker.check(simple_doc, section_map)
        assert report.section_coverage > 0
        assert report.section_coverage < 1.0  # 缺少根因分析

    def test_report_has_issues(self, simple_doc, mock_template):
        section_map = match_all_chapters(simple_doc, mock_template)
        checker = ContentChecker(mock_template)
        report = checker.check(simple_doc, section_map)
        assert report.total_issues > 0

    def test_multi_page_doc(self, multi_page_doc, mock_template):
        section_map = match_all_chapters(multi_page_doc, mock_template)
        checker = ContentChecker(mock_template)
        report = checker.check(multi_page_doc, section_map)
        assert isinstance(report, ContentReport)
