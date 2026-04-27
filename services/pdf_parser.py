"""PDF 解析器 — 基于 PyMuPDF (fitz) 的文字提取."""

from __future__ import annotations

import io
from typing import List

import fitz

from models.document import Page, ParsedDocument, Span, TextBlock


def normalize_font_name(name: str) -> str:
    """规范化字体名称：去空格、去横线、小写."""
    return name.lower().replace(" ", "").replace("-", "").replace("_", "")


def parse_pdf(file_bytes: bytes, filename: str = "") -> ParsedDocument:
    """解析 PDF 文件为 ParsedDocument.

    Args:
        file_bytes: PDF 文件的字节内容
        filename: 原始文件名（用于报告中展示）

    Returns:
        ParsedDocument 对象

    Raises:
        ValueError: PDF 损坏或无法解析时
    """
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"无法解析PDF文件: {e}") from e

    if doc.page_count == 0:
        doc.close()
        raise ValueError("PDF 文件为空（0页）")

    pages: List[Page] = []

    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        # 获取结构化文本
        text_dict = page.get_text("dict")

        page_width = page.rect.width
        page_height = page.rect.height

        blocks: List[TextBlock] = []

        for block in text_dict.get("blocks", []):
            if block.get("type") == 1:  # 图片块
                blocks.append(
                    TextBlock(
                        bbox=tuple(block.get("bbox", (0, 0, 0, 0))),
                        spans=(),
                        block_type=1,
                    )
                )
                continue

            spans: List[Span] = []
            for line in block.get("lines", []):
                for span_data in line.get("spans", []):
                    color = span_data.get("color", 0)
                    origin = tuple(span_data.get("origin", (0, 0)))

                    spans.append(
                        Span(
                            text=span_data.get("text", ""),
                            font=span_data.get("font", ""),
                            size=round(span_data.get("size", 0), 1),
                            color=color,
                            bbox=tuple(span_data.get("bbox", (0, 0, 0, 0))),
                            origin=origin,
                        )
                    )

            if spans:
                blocks.append(
                    TextBlock(
                        bbox=tuple(block.get("bbox", (0, 0, 0, 0))),
                        spans=tuple(spans),
                        block_type=block.get("type", 0),
                    )
                )

        pages.append(
            Page(
                page_number=page_idx + 1,
                width=page_width,
                height=page_height,
                blocks=tuple(blocks),
            )
        )

    page_count = doc.page_count
    doc.close()

    # 检测扫描版 PDF（文本块太少）
    total_text_blocks = sum(p.text_block_count for p in pages)
    if total_text_blocks == 0:
        raise ValueError(
            "PDF 中没有提取到文字内容。"
            "可能是扫描版 PDF（纯图片），建议使用 OCR 工具预处理。"
        )

    return ParsedDocument(
        filename=filename or "unknown.pdf",
        page_count=page_count,
        pages=tuple(pages),
    )


def get_document_stats(doc: ParsedDocument) -> dict:
    """获取文档统计信息."""
    total_spans = 0
    total_images = 0
    fonts_used = set()
    sizes_used = set()

    for page in doc.pages:
        for block in page.blocks:
            if block.block_type == 1:
                total_images += 1
            for span in block.spans:
                total_spans += 1
                if span.font:
                    fonts_used.add(normalize_font_name(span.font))
                if span.size > 0:
                    sizes_used.add(span.size)

    return {
        "pages": doc.page_count,
        "text_spans": total_spans,
        "images": total_images,
        "fonts_used": sorted(fonts_used),
        "font_sizes": sorted(sizes_used),
    }
