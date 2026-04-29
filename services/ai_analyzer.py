"""AI 分析器 — 支持 DeepSeek（OpenAI兼容）和 Anthropic 的内容质量分析."""

from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

from models.business_context import BusinessContext
from models.document import ParsedDocument
from models.review import AIDimension, AIReport, MeetingQuestion, MeetingQuestionsResult
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


MEETING_QUESTIONS_PROMPT = """你是一位经营分析会的主持人/高管顾问。你刚审核完一份事业部的经营分析汇报材料。

基于以下审核发现，请生成 4-6 个在经营分析会上可以提出的追问/质询问题。

## 审核发现

- 综合评分: {overall_score}/10
- 总体评价: {summary}
{dimension_summary}
{risk_text}

## 文档摘要
{document_summary}

{business_context}

## 提问要求

请生成三类问题：

### 第一类：精准追问（2-3个）
针对材料中**已有但不够深入**的内容，追问更深层信息。特征：
- 材料提到了某个数据/现象，但分析不透彻
- 根因分析停留在表面，缺少"为什么"的追问
- 措施列了但没有具体执行细节

示例风格：
- "材料提到升单率下降15%，但根因分析只说了'市场竞争激烈'。请问除了外部因素，内部在客户画像分群、升单话术标准化的自查中发现了什么？"
- "改善措施写了'加强培训'，请问培训对象是谁、培训频次多高、如何衡量培训效果？"

### 第二类：战略质询（1-2个）
从更高站位出发，挑战事业部的战略方向或执行逻辑。特征：
- 挑战假设：数据趋势是否暗示需要调整策略？
- 挑战优先级：资源分配是否合理？
- 挑战闭环：从问题到措施到结果，逻辑链条是否自洽？

示例风格：
- "进人量连续三个月下滑，但人力投入在增加。请问获客模型的效率拐点在哪里？是否需要重新评估渠道策略？"

### 第三类：风险预警追问（1个）
针对材料中**应该提及但未提及**的风险，或已识别风险的应对深度。

请严格按以下JSON格式输出（不要输出其他内容）：
{{
  "questions": [
    {{
      "category": "精准追问|战略质询|风险预警",
      "question": "具体问题文本",
      "rationale": "为什么问这个问题（基于材料的哪个发现）",
      "target_section": "针对文档的哪个章节/内容",
      "difficulty": "basic|advanced|expert"
    }}
  ],
  "opening_remark": "一段简短的开场白建议（30字以内），用于在会上引导提问节奏"
}}"""


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


def _extract_json(text: str) -> dict:
    """从 AI 响应中提取并解析 JSON，容忍常见格式问题."""
    # 优先提取 ```json ... ``` 代码块
    code_block = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', text)
    raw = code_block.group(1).strip() if code_block else text

    # 提取最外层 { }
    brace_match = re.search(r'\{[\s\S]*\}', raw)
    if not brace_match:
        raise ValueError(f"AI 响应中未找到 JSON: {text[:200]}")

    json_str = brace_match.group()

    # 尝试直接解析
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # 容错修复：移除尾部逗号（数组/对象末尾的 ,）和 JS 风格注释
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)  # 尾部逗号
    json_str = re.sub(r'//.*$', '', json_str, flags=re.MULTILINE)  # 单行注释
    json_str = re.sub(r'/\*[\s\S]*?\*/', '', json_str)  # 多行注释

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"AI 返回的 JSON 无法解析: {e}\n原始内容: {json_str[:300]}")


def _parse_ai_response(response_text: str) -> Tuple[List[AIDimension], float, str, List[str]]:
    """解析 AI 返回的 JSON."""
    data = _extract_json(response_text)

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


def _call_deepseek(
    system_prompt: str,
    user_message: str,
    api_key: Optional[str] = None,
) -> str:
    """调用 DeepSeek API（OpenAI 兼容接口）."""
    from openai import OpenAI

    key = api_key or settings.DEEPSEEK_API_KEY
    client = OpenAI(api_key=key, base_url=settings.DEEPSEEK_BASE_URL)
    response = client.chat.completions.create(
        model=settings.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        max_tokens=2048,
    )
    return response.choices[0].message.content


def _call_anthropic(
    system_prompt: str,
    user_message: str,
    api_key: Optional[str] = None,
) -> str:
    """调用 Anthropic API."""
    from anthropic import Anthropic

    key = api_key or settings.ANTHROPIC_API_KEY
    client = Anthropic(api_key=key)
    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def analyze_content(
    doc: ParsedDocument,
    section_map: Optional[SectionMap] = None,
    context: Optional[BusinessContext] = None,
    api_key: Optional[str] = None,
) -> AIReport:
    """调用 AI API 分析内容质量.

    根据settings.AI_PROVIDER选择DeepSeek或Anthropic。

    Args:
        doc: 解析后的文档
        section_map: 章节映射（可选）
        context: 业务上下文（可选）
        api_key: API 密钥（可选，默认从环境变量读取）

    Returns:
        AIReport 对象
    """
    provider = settings.AI_PROVIDER

    # 检查对应 provider 的 key
    if provider == "deepseek":
        key = api_key or settings.DEEPSEEK_API_KEY
        if not key:
            return AIReport(
                available=False,
                error_message="未配置 DEEPSEEK_API_KEY，AI 分析不可用",
            )
    elif provider == "anthropic":
        key = api_key or settings.ANTHROPIC_API_KEY
        if not key:
            return AIReport(
                available=False,
                error_message="未配置 ANTHROPIC_API_KEY，AI 分析不可用",
            )
    else:
        return AIReport(
            available=False,
            error_message=f"不支持的 AI 提供商: {provider}",
        )

    try:
        system_prompt = _build_system_prompt(context)
        user_message = _build_user_prompt(doc, section_map)

        if provider == "deepseek":
            response_text = _call_deepseek(system_prompt, user_message, api_key)
        else:
            response_text = _call_anthropic(system_prompt, user_message, api_key)

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


def _build_meeting_questions_user_prompt(
    ai_report: AIReport,
    doc: ParsedDocument,
    section_map: Optional[SectionMap] = None,
    context: Optional[BusinessContext] = None,
) -> str:
    """构建提问建议的用户消息."""
    # 维度评分摘要
    dim_lines = []
    for d in ai_report.dimensions:
        dim_lines.append(f"  - {d.name}: {d.score}/10 — {d.comment}")
    dimension_summary = "- 各维度评分:\n" + "\n".join(dim_lines) if dim_lines else ""

    # 风险提示
    risk_text = ""
    if ai_report.risk_warnings:
        risk_text = "- 风险提示:\n" + "\n".join(
            f"  - {r}" for r in ai_report.risk_warnings
        )

    # 文档摘要（复用已有逻辑）
    document_summary = _build_user_prompt(doc, section_map)

    # 业务上下文
    business_context = ""
    if context and context.to_prompt_text():
        business_context = f"## 事业部业务上下文\n{context.to_prompt_text()}"

    return MEETING_QUESTIONS_PROMPT.format(
        overall_score=ai_report.overall_score,
        summary=ai_report.summary,
        dimension_summary=dimension_summary,
        risk_text=risk_text,
        document_summary=document_summary,
        business_context=business_context,
    )


def _parse_meeting_questions(response_text: str) -> Tuple[Tuple[MeetingQuestion, ...], str]:
    """解析提问建议的 JSON 响应."""
    data = _extract_json(response_text)

    questions = tuple(
        MeetingQuestion(
            category=q.get("category", "精准追问"),
            question=q.get("question", ""),
            rationale=q.get("rationale", ""),
            target_section=q.get("target_section", ""),
            difficulty=q.get("difficulty", "basic"),
        )
        for q in data.get("questions", [])
    )

    opening_remark = data.get("opening_remark", "")

    return questions, opening_remark


def generate_meeting_questions(
    ai_report: AIReport,
    doc: ParsedDocument,
    section_map: Optional[SectionMap] = None,
    context: Optional[BusinessContext] = None,
    api_key: Optional[str] = None,
) -> MeetingQuestionsResult:
    """基于 AI 分析结果生成经营分析会提问建议.

    这是第二次 AI 调用，复用第一轮的分析结果和文档数据。

    Args:
        ai_report: 第一轮 AI 分析报告
        doc: 解析后的文档
        section_map: 章节映射（可选）
        context: 业务上下文（可选）
        api_key: API 密钥（可选）

    Returns:
        MeetingQuestionsResult
    """
    provider = settings.AI_PROVIDER

    # 检查 key
    if provider == "deepseek":
        key = api_key or settings.DEEPSEEK_API_KEY
        if not key:
            return MeetingQuestionsResult(
                available=False,
                error_message="未配置 DEEPSEEK_API_KEY",
            )
    elif provider == "anthropic":
        key = api_key or settings.ANTHROPIC_API_KEY
        if not key:
            return MeetingQuestionsResult(
                available=False,
                error_message="未配置 ANTHROPIC_API_KEY",
            )
    else:
        return MeetingQuestionsResult(
            available=False,
            error_message=f"不支持的 AI 提供商: {provider}",
        )

    try:
        user_message = _build_meeting_questions_user_prompt(
            ai_report, doc, section_map, context,
        )
        system_prompt = "你是一位经营分析会提问顾问，擅长从汇报材料中发现薄弱环节并生成精准的质询问题。请严格按 JSON 格式输出。"

        if provider == "deepseek":
            response_text = _call_deepseek(system_prompt, user_message, api_key)
        else:
            response_text = _call_anthropic(system_prompt, user_message, api_key)

        questions, opening_remark = _parse_meeting_questions(response_text)

        return MeetingQuestionsResult(
            available=True,
            questions=questions,
            opening_remark=opening_remark,
        )

    except Exception as e:
        return MeetingQuestionsResult(
            available=False,
            error_message=f"提问建议生成失败: {str(e)}",
        )
