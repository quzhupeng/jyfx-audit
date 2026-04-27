"""AI 分析器 — 基于 Claude API 的内容质量分析."""

from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

from anthropic import Anthropic

from models.business_context import BusinessContext
from models.document import ParsedDocument
from models.review import AIDimension, AIReport
from models.template import SectionMap, Template
from config import settings


SYSTEM_PROMPT_BASE = """你是一位资深的经营分析审核专家。你正在审核一份事业部的经营分析会汇报材料。

请从以下5个维度评估材料的内容质量，每个维度给出0-10分以及具体的评语和改进建议：

1. **完整性** (completeness): 是否覆盖了经营分析的完整闭环（现状→问题→根因→措施→计划）
2. **数据充分性** (data_sufficiency): 数据是否充分、准确、有对比（同比/环比/达成率）
3. **根因质量** (root_cause_quality): 对问题的分析是否深入本质，还是停留在表面
4. **措施可行性** (measure_feasibility): 改善措施是否具体、可执行、有时间节点和责任人
5. **风险识别** (risk_identification): 是否识别了关键风险和应对措施

请严格按以下JSON格式输出（不要输出其他内容）：
{
  "overall_score": 7.5,
  "summary": "一句话总体评价",
  "dimensions": [
    {"name": "完整性", "score": 8, "comment": "评价内容", "suggestions": ["建议1", "建议2"]},
    {"name": "数据充分性", "score": 7, "comment": "评价内容", "suggestions": ["建议1"]},
    {"name": "根因质量", "score": 6, "comment": "评价内容", "suggestions": ["建议1", "建议2"]},
    {"name": "措施可行性", "score": 8, "comment": "评价内容", "suggestions": []},
    {"name": "风险识别", "score": 7, "comment": "评价内容", "suggestions": ["建议1"]}
  ],
  "risk_warnings": ["风险描述1", "风险描述2"]
}"""


def _build_system_prompt(context: Optional[BusinessContext] = None) -> str:
    """构建系统 prompt."""
    prompt = SYSTEM_PROMPT_BASE
    if context and context.analysis_prompt_extension:
        prompt += "\n\n" + context.to_prompt_text()
    return prompt


def _build_user_prompt(
    doc: ParsedDocument,
    section_map: Optional[SectionMap] = None,
    max_chars_per_section: int = 2000,
) -> str:
    """构建用户消息（文档内容摘要）."""
    parts = [f"## 汇报材料摘要\n文件名：{doc.filename}\n总页数：{doc.page_count}\n"]

    if section_map:
        parts.append("### 章节结构")
        for ch in section_map.sections:
            status = "✓" if ch.matched else "✗"
            parts.append(
                f"- {status} {ch.section_name} "
                f"(置信度{ch.confidence:.0%}, "
                f"第{ch.page_start}-{ch.page_end}页)"
            )

    parts.append("\n### 文档内容\n")

    # 按章节提取文本（有章节映射时）或整体文本
    if section_map:
        for ch in section_map.sections:
            if not ch.matched:
                continue
            parts.append(f"\n#### {ch.section_name}")
            section_text = ""
            for pn in range(ch.page_start, min(ch.page_end + 1, doc.page_count + 1)):
                section_text += doc.get_page_text(pn) + "\n"
            if len(section_text) > max_chars_per_section:
                section_text = section_text[:max_chars_per_section] + "\n...(内容已截断)"
            parts.append(section_text)
    else:
        # 无章节映射：整体截断
        full_text = doc.all_text
        if len(full_text) > max_chars_per_section * 4:
            full_text = full_text[:max_chars_per_section * 4] + "\n...(内容已截断)"
        parts.append(full_text)

    return "\n".join(parts)


def _parse_ai_response(response_text: str) -> Tuple[List[AIDimension], float, str, List[str]]:
    """解析 AI 返回的 JSON."""
    # 尝试提取 JSON 块
    json_match = re.search(r'\{[\s\S]*\}', response_text)
    if not json_match:
        raise ValueError(f"AI 响应中未找到 JSON: {response_text[:200]}")

    data = json.loads(json_match.group())

    dimensions = tuple(
        AIDimension(
            name=d.get("name", ""),
            score=float(d.get("score", 0)),
            comment=d.get("comment", ""),
            suggestions=tuple(d.get("suggestions", [])),
        )
        for d in data.get("dimensions", [])
    )

    overall = float(data.get("overall_score", 0))
    summary = data.get("summary", "")
    risk_warnings = tuple(data.get("risk_warnings", []))

    return dimensions, overall, summary, risk_warnings


def analyze_content(
    doc: ParsedDocument,
    section_map: Optional[SectionMap] = None,
    context: Optional[BusinessContext] = None,
    api_key: Optional[str] = None,
) -> AIReport:
    """调用 Claude API 分析内容质量.

    Args:
        doc: 解析后的文档
        section_map: 章节映射（可选）
        context: 业务上下文（可选）
        api_key: API 密钥（可选，默认从环境变量读取）

    Returns:
        AIReport 对象
    """
    key = api_key or settings.ANTHROPIC_API_KEY
    if not key:
        return AIReport(
            available=False,
            error_message="未配置 ANTHROPIC_API_KEY，AI 分析不可用",
        )

    try:
        client = Anthropic(api_key=key)
        system_prompt = _build_system_prompt(context)
        user_message = _build_user_prompt(doc, section_map)

        response = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        response_text = response.content[0].text

        dimensions, overall, summary, risks = _parse_ai_response(response_text)

        return AIReport(
            available=True,
            dimensions=dimensions,
            overall_score=round(overall, 1),
            summary=summary,
            risk_warnings=risks,
        )

    except Exception as e:
        return AIReport(
            available=False,
            error_message=f"AI 分析失败: {str(e)}",
        )
