"""ParsedDocument, Page, TextBlock, Span — 从PDF解析出的文档模型."""

from __future__ import annotations

from typing import Tuple

from pydantic import BaseModel, Field


class Span(BaseModel):
    """单个文字片段的属性."""

    text: str = Field(description="文字内容")
    font: str = Field(default="", description="字体名称")
    size: float = Field(default=0.0, description="字号(pts)")
    color: int = Field(default=0, description="sRGB 编码颜色 (整数)")
    bbox: Tuple[float, float, float, float] = Field(
        default=(0, 0, 0, 0), description="边界框 (x0, y0, x1, y1)"
    )
    origin: Tuple[float, float] = Field(
        default=(0, 0), description="文字起点坐标"
    )

    model_config = {"frozen": True}


class TextBlock(BaseModel):
    """一个文本块，包含多个 Span."""

    bbox: Tuple[float, float, float, float] = Field(
        default=(0, 0, 0, 0), description="文本块边界框"
    )
    spans: Tuple[Span, ...] = Field(default_factory=tuple, description="包含的文字片段")
    block_type: int = Field(default=0, description="块类型 (0=text, 1=image)")

    model_config = {"frozen": True}

    @property
    def full_text(self) -> str:
        return "".join(s.text for s in self.spans)


class Page(BaseModel):
    """PDF 单页."""

    page_number: int = Field(description="页码 (从1开始)")
    width: float = Field(default=0.0, description="页面宽度")
    height: float = Field(default=0.0, description="页面高度")
    blocks: Tuple[TextBlock, ...] = Field(
        default_factory=tuple, description="页面中的所有文本块"
    )

    model_config = {"frozen": True}

    @property
    def all_text(self) -> str:
        return "".join(b.full_text for b in self.blocks)

    @property
    def text_block_count(self) -> int:
        return len([b for b in self.blocks if b.block_type == 0])


class ParsedDocument(BaseModel):
    """完整的解析后文档."""

    filename: str = Field(default="", description="原始文件名")
    page_count: int = Field(default=0, description="总页数")
    pages: Tuple[Page, ...] = Field(default_factory=tuple, description="所有页面")

    model_config = {"frozen": True}

    @property
    def all_text(self) -> str:
        return "\n".join(p.all_text for p in self.pages)

    @property
    def total_blocks(self) -> int:
        return sum(len(p.blocks) for p in self.pages)

    def get_page_text(self, page_num: int) -> str:
        """获取指定页码的文本 (1-indexed)."""
        for p in self.pages:
            if p.page_number == page_num:
                return p.all_text
        return ""
