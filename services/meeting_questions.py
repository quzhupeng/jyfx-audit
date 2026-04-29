"""经营分析会提问建议生成器 — 独立模块，避免模块缓存冲突."""

from __future__ import annotations

import json
import re
from typing import Optional, Tuple

from models.business_context import BusinessContext
from models.document import ParsedDocument
from models.review import AIReport, MeetingQuestion, MeetingQuestionsResult
from models.template import SectionMap
from config import settings


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


def _extract_json(text: str) -> dict:
    """从 AI 响应中提取并解析 JSON，容忍常见格式问题."""
    code_block = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', text)
    raw = code_block.group(1).strip() if code_block else text

    brace_match = re.search(r'\{[\s\S]*\}', raw)
    if not brace_match:
        raise ValueError(f"AI 响应中未找到 JSON: {text[:200]}")

    json_str = brace_match.group()

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # 容错：尾部逗号、注释
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
    json_str = re.sub(r'//.*$', '', json_str, flags=re.MULTILINE)
    json_str = re.sub(r'/\*[\s\S]*?\*/', '', json_str)

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"AI 返回的 JSON 无法解析: {e}\n原始内容: {json_str[:300]}")


def _build_doc_summary(doc: ParsedDocument, section_map: Optional[SectionMap] = None) -> str:
    """构建文档内容摘要."""
    max_chars = 2000
    parts = [f"文件名：{doc.filename}\n总页数：{doc.page_count}\n"]

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

    if section_map:
        for ch in section_map.sections:
            if not ch.matched:
                continue
            parts.append(f"\n#### {ch.section_name}")
            section_text = ""
            for pn in range(ch.page_start, min(ch.page_end + 1, doc.page_count + 1)):
                section_text += doc.get_page_text(pn) + "\n"
            if len(section_text) > max_chars:
                section_text = section_text[:max_chars] + "\n...(内容已截断)"
            parts.append(section_text)
    else:
        full_text = doc.all_text
        if len(full_text) > max_chars * 4:
            full_text = full_text[:max_chars * 4] + "\n...(内容已截断)"
        parts.append(full_text)

    return "\n".join(parts)


def _call_llm(system_prompt: str, user_message: str, api_key: Optional[str] = None) -> str:
    """调用 LLM API."""
    provider = settings.AI_PROVIDER

    if provider == "deepseek":
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
    else:
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


def generate_meeting_questions(
    ai_report: AIReport,
    doc: ParsedDocument,
    section_map: Optional[SectionMap] = None,
    context: Optional[BusinessContext] = None,
    api_key: Optional[str] = None,
) -> MeetingQuestionsResult:
    """基于 AI 分析结果生成经营分析会提问建议.

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

    if provider == "deepseek":
        key = api_key or settings.DEEPSEEK_API_KEY
        if not key:
            return MeetingQuestionsResult(available=False, error_message="未配置 DEEPSEEK_API_KEY")
    elif provider == "anthropic":
        key = api_key or settings.ANTHROPIC_API_KEY
        if not key:
            return MeetingQuestionsResult(available=False, error_message="未配置 ANTHROPIC_API_KEY")
    else:
        return MeetingQuestionsResult(available=False, error_message=f"不支持的 AI 提供商: {provider}")

    try:
        # 构建维度评分摘要
        dim_lines = [f"  - {d.name}: {d.score}/10 — {d.comment}" for d in ai_report.dimensions]
        dimension_summary = "- 各维度评分:\n" + "\n".join(dim_lines) if dim_lines else ""

        risk_text = ""
        if ai_report.risk_warnings:
            risk_text = "- 风险提示:\n" + "\n".join(f"  - {r}" for r in ai_report.risk_warnings)

        document_summary = _build_doc_summary(doc, section_map)

        business_context = ""
        if context and context.to_prompt_text():
            business_context = f"## 事业部业务上下文\n{context.to_prompt_text()}"

        user_message = MEETING_QUESTIONS_PROMPT.format(
            overall_score=ai_report.overall_score,
            summary=ai_report.summary,
            dimension_summary=dimension_summary,
            risk_text=risk_text,
            document_summary=document_summary,
            business_context=business_context,
        )

        system_prompt = "你是一位经营分析会提问顾问，擅长从汇报材料中发现薄弱环节并生成精准的质询问题。请严格按 JSON 格式输出。"

        response_text = _call_llm(system_prompt, user_message, api_key)
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

        return MeetingQuestionsResult(
            available=True,
            questions=questions,
            opening_remark=data.get("opening_remark", ""),
        )

    except Exception as e:
        return MeetingQuestionsResult(
            available=False,
            error_message=f"提问建议生成失败: {str(e)}",
        )
