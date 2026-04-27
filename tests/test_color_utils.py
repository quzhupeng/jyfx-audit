"""测试颜色工具."""

from __future__ import annotations

from utils.color_utils import (
    srgb_to_rgb,
    rgb_to_srgb,
    hex_to_rgb,
    is_color_within_tolerance,
    color_distance,
    normalize_color_name,
    format_srgb,
)


class TestSrgbConversion:
    def test_black(self):
        assert srgb_to_rgb(0x000000) == (0, 0, 0)

    def test_white(self):
        assert srgb_to_rgb(0xFFFFFF) == (255, 255, 255)

    def test_red(self):
        assert srgb_to_rgb(0xFF0000) == (255, 0, 0)

    def test_rgb_to_srgb_roundtrip(self):
        r, g, b = 100, 150, 200
        srgb = rgb_to_srgb(r, g, b)
        assert srgb_to_rgb(srgb) == (r, g, b)


class TestHexToRgb:
    def test_with_hash(self):
        assert hex_to_rgb("#FF0000") == (255, 0, 0)

    def test_without_hash(self):
        assert hex_to_rgb("00FF00") == (0, 255, 0)

    def test_gray(self):
        assert hex_to_rgb("#333333") == (51, 51, 51)


class TestColorWithinTolerance:
    def test_exact_match(self):
        assert is_color_within_tolerance(0x000000, "#000000", tolerance=0)

    def test_small_deviation(self):
        # 0x010101 vs #000000 — 每个通道差1
        assert is_color_within_tolerance(0x010101, "#000000", tolerance=5)

    def test_large_deviation(self):
        assert not is_color_within_tolerance(0xFF0000, "#000000", tolerance=5)

    def test_default_tolerance(self):
        # 0x440000 与 #333333 差 0x11=17 在默认容差30内
        assert is_color_within_tolerance(0x333333, "#333333", tolerance=0)
        assert not is_color_within_tolerance(0x555555, "#333333", tolerance=10)


class TestColorDistance:
    def test_same_color_zero_distance(self):
        assert color_distance(0xFF0000, 0xFF0000) == 0.0

    def test_black_white_max_distance(self):
        d = color_distance(0x000000, 0xFFFFFF)
        assert d > 400


class TestNormalizeColorName:
    def test_spaces_removed(self):
        assert normalize_color_name("Microsoft YaHei") == "microsoftyahei"

    def test_dashes_removed(self):
        assert normalize_color_name("Times-New-Roman") == "timesnewroman"

    def test_underscores_removed(self):
        assert normalize_color_name("some_font") == "somefont"


class TestFormatSrgb:
    def test_black(self):
        assert format_srgb(0x000000) == "#000000"

    def test_white(self):
        assert format_srgb(0xFFFFFF) == "#FFFFFF"

    def test_custom(self):
        assert format_srgb(0x1A2B3C) == "#1A2B3C"
