"""RGB 颜色工具：转换、容差检查、色差计算."""

from __future__ import annotations

from typing import Tuple


def srgb_to_rgb(srgb: int) -> Tuple[int, int, int]:
    """将 sRGB 编码整数转换为 (R, G, B) 元组."""
    r = (srgb >> 16) & 0xFF
    g = (srgb >> 8) & 0xFF
    b = srgb & 0xFF
    return (r, g, b)


def rgb_to_srgb(r: int, g: int, b: int) -> int:
    """将 (R, G, B) 元组转换为 sRGB 编码整数."""
    return (r << 16) | (g << 8) | b


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """将十六进制颜色字符串转换为 (R, G, B) 元组.

    Args:
        hex_color: 如 '#333333' 或 '333333'
    """
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def is_color_within_tolerance(
    actual_srgb: int,
    expected_hex: str,
    tolerance: int = 30,
) -> bool:
    """检查实际颜色是否在期望颜色的容差范围内.

    Args:
        actual_srgb: 实际的 sRGB 编码颜色
        expected_hex: 期望的十六进制颜色
        tolerance: 每个通道的容差值 (0-255)

    Returns:
        True 如果每个通道差值都在容差内
    """
    actual_rgb = srgb_to_rgb(actual_srgb)
    expected_rgb = hex_to_rgb(expected_hex)
    return all(
        abs(a - e) <= tolerance
        for a, e in zip(actual_rgb, expected_rgb)
    )


def color_distance(srgb1: int, srgb2: int) -> float:
    """计算两个 sRGB 颜色之间的欧几里得距离."""
    r1, g1, b1 = srgb_to_rgb(srgb1)
    r2, g2, b2 = srgb_to_rgb(srgb2)
    return ((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5


def normalize_color_name(name: str) -> str:
    """规范化颜色/字体名称，用于模糊匹配.

    - 转小写
    - 移除空格和横线
    """
    return name.lower().replace(" ", "").replace("-", "").replace("_", "")


def format_srgb(srgb: int) -> str:
    """格式化 sRGB 为可读的十六进制字符串."""
    r, g, b = srgb_to_rgb(srgb)
    return f"#{r:02X}{g:02X}{b:02X}"
