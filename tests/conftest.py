"""测试共享 fixture — 编程生成测试 PDF."""

from __future__ import annotations

import io

import fitz
import pytest

from models.document import ParsedDocument
from models.template import (
    ContentRule,
    DetectionRule,
    FormatRule,
    SectionDefinition,
    Template,
)
from services.pdf_parser import parse_pdf


CJK_FONT = "china-s"  # PyMuPDF 内置简体中文字体


def create_test_pdf_bytes(
    pages_data: list[list[tuple[str, str, float, tuple]]],
    use_cjk: bool = True,
) -> bytes:
    """用 fitz 编程生成测试 PDF.

    Args:
        pages_data: 每页是一个列表，每项 (text, font, size, color)
        use_cjk: 是否使用中文字体 (china-s)
        color 为 (r, g, b) 元组，每个值 0-255 整数
    """
    doc = fitz.open()
    for page_idx, page_spans in enumerate(pages_data):
        page = doc.new_page(width=595, height=842)
        y = 50
        for text, font, size, color in page_spans:
            if not text.strip() or size <= 0:
                continue
            rgb = (
                (color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)
                if isinstance(color, tuple) and max(color) > 1
                else color
            ) if isinstance(color, tuple) else None
            actual_font = font if font else (CJK_FONT if use_cjk else "helv")
            page.insert_text(
                (50, y),
                text,
                fontname=actual_font,
                fontsize=size,
                color=rgb,
            )
            y += size * 1.5
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


@pytest.fixture
def simple_pdf_bytes():
    """简单的测试 PDF."""
    return create_test_pdf_bytes([
        [("封面标题", "", 36, (0, 0, 0)), ("经营分析汇报", "", 16, (0, 0, 0))],
        [("目录", "", 24, (0, 0, 0)), ("1. 经营概况", "", 14, (0, 0, 0))],
        [("经营概况", "", 28, (0, 0, 0)), ("收入达成率 95%", "", 14, (0, 0, 0))],
    ])


@pytest.fixture
def simple_doc(simple_pdf_bytes):
    """解析后的简单文档."""
    return parse_pdf(simple_pdf_bytes, "test.pdf")


@pytest.fixture
def empty_pdf_bytes():
    """空页面的 PDF."""
    return create_test_pdf_bytes([
        [("x", "", 10, (0, 0, 0))],
    ])


@pytest.fixture
def mock_template():
    """模拟模板."""
    sections = [
        SectionDefinition(
            id="cover",
            name="封面",
            order=0,
            essential=False,
            detection=DetectionRule(
                keywords=("经营分析", "汇报"),
                match_mode="any",
                search_scope="first_page",
            ),
            content_rules=ContentRule(min_pages=1, min_text_length=5),
        ),
        SectionDefinition(
            id="toc",
            name="目录",
            order=1,
            essential=False,
            detection=DetectionRule(
                keywords=("目录",),
                match_mode="any",
                search_scope="first_3_pages",
            ),
            content_rules=ContentRule(min_pages=1, min_text_length=10),
        ),
        SectionDefinition(
            id="business_overview",
            name="经营概况",
            order=2,
            essential=True,
            detection=DetectionRule(
                keywords=("经营概况", "达成率"),
                match_mode="any",
                search_scope="first_3_pages",
            ),
            format=FormatRule(
                allowed_fonts=("china-s",),
                font_size_range=(10, 48),
                body_size_range=(10, 28),
                title_size_range=(22, 48),
                allowed_colors=("#000000", "#333333"),
                color_tolerance=30,
            ),
            content_rules=ContentRule(
                min_pages=1,
                required_elements=("达成率",),
                requires_data=True,
                min_text_length=50,
            ),
        ),
        SectionDefinition(
            id="root_cause_analysis",
            name="根因分析",
            order=3,
            essential=True,
            detection=DetectionRule(
                keywords=("根因分析", "原因分析", "问题分析"),
                match_mode="any",
                search_scope="full",
            ),
            content_rules=ContentRule(
                min_pages=1,
                required_elements=("原因",),
                min_text_length=50,
            ),
        ),
    ]
    return Template(
        name="测试模板",
        version="1.0",
        sections=tuple(sections),
    )


@pytest.fixture
def multi_page_pdf_bytes():
    """多页测试 PDF."""
    pages = []
    # 封面
    pages.append([
        ("直销事业部", "", 36, (0, 0, 0)),
        ("2025年Q1经营分析汇报", "", 18, (0, 0, 0)),
    ])
    # 目录
    pages.append([
        ("目录", "", 24, (0, 0, 0)),
        ("经营概况", "", 14, (0, 0, 0)),
        ("根因分析", "", 14, (0, 0, 0)),
    ])
    # 经营概况
    pages.append([
        ("经营概况", "", 28, (0, 0, 0)),
        ("销售收入达成率95%，同比增长12%", "", 14, (0, 0, 0)),
        ("利润达成率88%", "", 14, (0, 0, 0)),
    ])
    # 根因分析
    pages.append([
        ("根因分析", "", 28, (0, 0, 0)),
        ("主要原因是市场环境变化和竞争对手降价", "", 14, (0, 0, 0)),
    ])
    return create_test_pdf_bytes(pages)


@pytest.fixture
def multi_page_doc(multi_page_pdf_bytes):
    """解析后的多页文档."""
    return parse_pdf(multi_page_pdf_bytes, "multi_test.pdf")
