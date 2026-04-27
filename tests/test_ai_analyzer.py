"""测试 AI 分析器."""

from __future__ import annotations

import json

import pytest

from services.ai_analyzer import (
    _build_system_prompt,
    _build_user_prompt,
    _parse_ai_response,
    analyze_content,
)
from models.business_context import BusinessContext
from models.review import AIReport


class TestBuildSystemPrompt:
    def test_base_prompt(self):
        prompt = _build_system_prompt(None)
        assert "经营分析审核专家" in prompt
        assert "完整性" in prompt
        assert "数据充分性" in prompt

    def test_with_business_context(self):
        ctx = BusinessContext(
            department="测试事业部",
            analysis_prompt_extension="测试扩展内容",
        )
        prompt = _build_system_prompt(ctx)
        assert "测试事业部" in prompt
        assert "测试扩展内容" in prompt


class TestBuildUserPrompt:
    def test_basic_prompt(self, simple_doc):
        prompt = _build_user_prompt(simple_doc)
        assert simple_doc.filename in prompt
        assert "文档内容" in prompt
        assert "封面标题" in prompt

    def test_with_section_map(self, simple_doc, mock_template):
        from services.template_engine import match_all_chapters
        section_map = match_all_chapters(simple_doc, mock_template)
        prompt = _build_user_prompt(simple_doc, section_map)
        assert "封面" in prompt
        assert "目录" in prompt


class TestParseAiResponse:
    def test_parse_valid_json(self):
        response = json.dumps({
            "overall_score": 7.5,
            "summary": "总体评价",
            "dimensions": [
                {"name": "完整性", "score": 8, "comment": "好", "suggestions": ["建议1"]},
                {"name": "数据充分性", "score": 7, "comment": "可以", "suggestions": []},
                {"name": "根因质量", "score": 6, "comment": "一般", "suggestions": ["深挖"]},
                {"name": "措施可行性", "score": 8, "comment": "可行", "suggestions": []},
                {"name": "风险识别", "score": 7, "comment": "到位", "suggestions": ["注意"]},
            ],
            "risk_warnings": ["风险1", "风险2"],
        })
        dimensions, overall, summary, risks = _parse_ai_response(response)
        assert overall == 7.5
        assert summary == "总体评价"
        assert len(dimensions) == 5
        assert len(risks) == 2

    def test_parse_json_with_surrounding_text(self):
        response = '这是分析结果：\n```json\n{"overall_score": 6.0, "summary": "ok", "dimensions": [], "risk_warnings": []}\n```'
        dimensions, overall, summary, risks = _parse_ai_response(response)
        assert overall == 6.0

    def test_parse_invalid_returns_error(self):
        with pytest.raises((ValueError, json.JSONDecodeError)):
            _parse_ai_response("这不是 JSON")


class TestAnalyzeContent:
    def test_no_api_key_returns_unavailable(self, simple_doc):
        report = analyze_content(simple_doc, api_key="")
        assert isinstance(report, AIReport)
        assert not report.available
        assert "未配置" in report.error_message
