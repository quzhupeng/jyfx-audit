"""YAML 配置加载器：加载模板和业务上下文."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

import yaml

from models.template import (
    ContentRule,
    DetectionRule,
    FormatRule,
    SectionDefinition,
    Template,
)
from models.business_context import (
    BusinessContext,
    FocusArea,
    KPI,
    RiskFactor,
)

# 项目根目录
ROOT_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT_DIR / "templates"


def _parse_detection_rule(data: dict) -> DetectionRule:
    return DetectionRule(
        keywords=tuple(data.get("keywords", [])),
        match_mode=data.get("match_mode", "any"),
        search_scope=data.get("search_scope", "first_page"),
        weight=data.get("weight", 1.0),
    )


def _parse_format_rule(data: dict) -> FormatRule:
    return FormatRule(
        allowed_fonts=tuple(data.get("allowed_fonts", [])),
        font_size_range=tuple(data.get("font_size_range", [10, 48])),
        title_size_range=tuple(data.get("title_size_range", [22, 48])),
        body_size_range=tuple(data.get("body_size_range", [10, 28])),
        allowed_colors=tuple(data.get("allowed_colors", [])),
        color_tolerance=data.get("color_tolerance", 30),
        title_top_ratio=data.get("title_top_ratio", 0.15),
        margin_threshold=data.get("margin_threshold", 20.0),
    )


def _parse_content_rule(data: dict) -> ContentRule:
    return ContentRule(
        min_pages=data.get("min_pages", 1),
        required_elements=tuple(data.get("required_elements", [])),
        requires_data=data.get("requires_data", False),
        requires_chart=data.get("requires_chart", False),
        min_text_length=data.get("min_text_length", 50),
        min_text_length_section=data.get("min_text_length_section", 100),
        depth_indicators=tuple(data.get("depth_indicators", [])),
    )


def _parse_section(data: dict, order: int) -> SectionDefinition:
    return SectionDefinition(
        id=data["id"],
        name=data.get("name", data["id"]),
        order=order,
        essential=data.get("essential", True),
        detection=_parse_detection_rule(data.get("detection", {})),
        format=_parse_format_rule(data.get("format", {})),
        content_rules=_parse_content_rule(data.get("content_rules", {})),
        description=data.get("description", ""),
    )


def load_template(path: str = None) -> Template:
    """加载审核模板.

    Args:
        path: YAML 文件路径。为 None 时使用默认模板。

    Returns:
        Template 对象
    """
    if path is None:
        path = TEMPLATES_DIR / "default_template.yaml"
    else:
        path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"模板文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    sections = tuple(
        _parse_section(s, i)
        for i, s in enumerate(data.get("sections", []))
    )

    return Template(
        name=data.get("name", "默认模板"),
        version=str(data.get("version", "1.0")),
        sections=sections,
        metadata=data.get("metadata", {}),
    )


def _parse_focus_area(data: dict) -> FocusArea:
    return FocusArea(
        area=data.get("area", ""),
        kpis=tuple(
            KPI(
                name=k.get("name", ""),
                direction=k.get("direction", "higher_better"),
                description=k.get("description", ""),
                threshold=str(k.get("threshold", "")),
            )
            for k in data.get("kpis", [])
        ),
        weight=float(data.get("weight", 1.0)),
    )


def _parse_risk_factor(data: dict) -> RiskFactor:
    return RiskFactor(
        name=data.get("name", ""),
        description=data.get("description", ""),
        threshold=str(data.get("threshold", "")),
        severity=data.get("severity", "medium"),
    )


def load_business_context(department: str) -> BusinessContext:
    """加载事业部业务上下文.

    Args:
        department: 事业部标识，如 'direct_sales', 'raw_materials' 等

    Returns:
        BusinessContext 对象
    """
    # 尝试加载对应配置文件
    config_path = TEMPLATES_DIR / "business_contexts" / f"{department}.yaml"

    if not config_path.exists():
        # 返回一个基本的空上下文
        return BusinessContext(
            department=department,
            description=f"{department} (未配置详细业务上下文)",
        )

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return BusinessContext(
        department=data.get("department", department),
        description=data.get("description", ""),
        focus_areas=tuple(
            _parse_focus_area(fa) for fa in data.get("focus_areas", [])
        ),
        terminology=tuple(data.get("terminology", [])),
        content_expectations=tuple(data.get("content_expectations", [])),
        risk_factors=tuple(
            _parse_risk_factor(rf) for rf in data.get("risk_factors", [])
        ),
        analysis_prompt_extension=data.get("analysis_prompt_extension", ""),
    )


def list_available_templates() -> List[str]:
    """列出所有可用的模板文件."""
    if not TEMPLATES_DIR.exists():
        return []
    return [f.name for f in TEMPLATES_DIR.glob("*.yaml")]


def list_business_contexts() -> List[str]:
    """列出所有已配置的事业部."""
    ctx_dir = TEMPLATES_DIR / "business_contexts"
    if not ctx_dir.exists():
        return []
    return [f.stem for f in ctx_dir.glob("*.yaml")]
