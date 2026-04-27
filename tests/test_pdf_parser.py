"""测试 PDF 解析器."""

from __future__ import annotations

import pytest

from services.pdf_parser import parse_pdf, get_document_stats, normalize_font_name
from models.document import ParsedDocument, Page, TextBlock, Span


class TestNormalizeFontName:
    def test_normalize_spaces(self):
        assert normalize_font_name("Microsoft YaHei") == "microsoftyahei"

    def test_normalize_dashes(self):
        assert normalize_font_name("Microsoft-YaHei") == "microsoftyahei"

    def test_normalize_case(self):
        assert normalize_font_name("HELV") == "helv"


class TestParsePdf:
    def test_parse_simple_pdf(self, simple_pdf_bytes):
        doc = parse_pdf(simple_pdf_bytes, "test.pdf")
        assert doc.filename == "test.pdf"
        assert doc.page_count == 3
        assert len(doc.pages) == 3

    def test_first_page_content(self, simple_doc):
        page_1 = simple_doc.pages[0]
        assert page_1.page_number == 1
        assert "封面标题" in page_1.all_text
        assert "经营分析汇报" in page_1.all_text

    def test_page_dimensions(self, simple_doc):
        page = simple_doc.pages[0]
        assert page.width > 0
        assert page.height > 0

    def test_spans_have_text(self, simple_doc):
        for page in simple_doc.pages:
            for block in page.blocks:
                if block.block_type == 0:
                    for span in block.spans:
                        assert span.text is not None

    def test_empty_page_pdf(self, empty_pdf_bytes):
        doc = parse_pdf(empty_pdf_bytes, "empty.pdf")
        assert doc.page_count == 1

    def test_invalid_pdf(self):
        with pytest.raises(ValueError, match="无法解析"):
            parse_pdf(b"not a pdf", "bad.pdf")

    def test_get_document_stats(self, simple_doc):
        stats = get_document_stats(simple_doc)
        assert stats["pages"] == 3
        assert stats["text_spans"] > 0
        assert "fonts_used" in stats
        assert "font_sizes" in stats

    def test_get_page_text(self, simple_doc):
        text = simple_doc.get_page_text(1)
        assert len(text) > 0

    def test_get_page_text_out_of_range(self, simple_doc):
        assert simple_doc.get_page_text(99) == ""

    def test_all_text(self, simple_doc):
        text = simple_doc.all_text
        assert "封面标题" in text

    def test_total_blocks(self, simple_doc):
        assert simple_doc.total_blocks > 0
