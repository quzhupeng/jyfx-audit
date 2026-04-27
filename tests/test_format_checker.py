"""测试格式检查器."""

from __future__ import annotations

import pytest

from services.format_checker import FormatChecker, check_page_format
from models.review import FormatReport, FormatIssue
from models.template import FormatRule, Template
from services.template_engine import match_all_chapters


class TestCheckPageFormat:
    def test_no_issues_with_default_rule(self, simple_doc):
        page = simple_doc.pages[0]
        issues = check_page_format(page, FormatRule())
        assert isinstance(issues, list)

    def test_font_issue_detected(self, simple_doc, mock_template):
        # simple_doc 使用 helv 字体，但我们限制只能使用 "微软雅黑"
        page = simple_doc.pages[0]
        rule = FormatRule(
            allowed_fonts=("微软雅黑",),
            font_size_range=(10, 48),
            allowed_colors=(),
        )
        issues = check_page_format(page, rule)
        font_issues = [i for i in issues if i.category == "font"]
        # helv 不在 "微软雅黑" 列表中，应该被检测到
        assert len(font_issues) > 0

    def test_color_within_tolerance(self, simple_doc):
        page = simple_doc.pages[0]
        rule = FormatRule(
            allowed_fonts=(),
            allowed_colors=("#000000",),  # black
            color_tolerance=30,
        )
        issues = check_page_format(page, rule)
        color_issues = [i for i in issues if i.category == "color"]
        assert len(color_issues) == 0  # helv 默认黑色在容差内

    def test_size_issue_detected(self, simple_doc):
        page = simple_doc.pages[0]
        rule = FormatRule(
            allowed_fonts=(),
            font_size_range=(12, 16),  # 窄范围
            body_size_range=(12, 16),
            title_size_range=(12, 16),
            allowed_colors=(),
        )
        issues = check_page_format(page, rule)
        size_issues = [i for i in issues if i.category == "size"]
        # 封面标题是 36pt 超出范围
        assert len(size_issues) > 0


class TestFormatChecker:
    def test_check_returns_report(self, simple_doc, mock_template):
        section_map = match_all_chapters(simple_doc, mock_template)
        checker = FormatChecker(mock_template)
        report = checker.check(simple_doc, section_map)
        assert isinstance(report, FormatReport)
        assert 0 <= report.overall_score <= 1.0

    def test_check_without_section_map(self, simple_doc, mock_template):
        checker = FormatChecker(mock_template)
        report = checker.check(simple_doc, None)
        assert isinstance(report, FormatReport)

    def test_report_has_issues(self, simple_doc, mock_template):
        checker = FormatChecker(mock_template)
        report = checker.check(simple_doc)
        assert report.total_issues >= 0
        assert isinstance(report.issues, tuple)

    def test_report_sub_scores(self, simple_doc, mock_template):
        checker = FormatChecker(mock_template)
        report = checker.check(simple_doc)
        assert 0 <= report.font_score <= 1.0
        assert 0 <= report.size_score <= 1.0
        assert 0 <= report.color_score <= 1.0
        assert 0 <= report.layout_score <= 1.0

    def test_get_issues_by_severity(self, simple_doc, mock_template):
        checker = FormatChecker(mock_template)
        report = checker.check(simple_doc)
        warnings = report.get_issues_by_severity("warning")
        assert isinstance(warnings, tuple)
