"""报告生成器 — 合并格式审核、内容审核、AI 分析为综合报告."""

from __future__ import annotations

import datetime
from typing import Optional

from models.business_context import BusinessContext
from models.document import ParsedDocument
from models.review import AIReport, ContentReport, FormatReport, ReviewReport
from models.template import SectionMap, Template


class ReportGenerator:
    """综合报告生成器."""

    def __init__(self, template: Template):
        self.template = template

    def merge(
        self,
        filename: str,
        department: str,
        format_report: FormatReport,
        content_report: ContentReport,
        ai_report: Optional[AIReport] = None,
    ) -> ReviewReport:
        """合并各类报告为综合审核报告.

        Args:
            filename: 原始文件名
            department: 事业部名称
            format_report: 格式审核报告
            content_report: 内容审核报告
            ai_report: AI 分析报告（可选）

        Returns:
            ReviewReport
        """
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 计算综合评分 (100分制)
        format_weight = 0.25
        content_weight = 0.35
        ai_weight = 0.40

        format_score = format_report.overall_score * 100
        content_score = content_report.overall_score * 100
        ai_score = (ai_report.overall_score / 10.0 * 100) if ai_report and ai_report.available else 70

        overall = (
            format_score * format_weight
            + content_score * content_weight
            + ai_score * ai_weight
        )

        # 判断状态
        critical_issues = content_report.get_critical_issues()
        if critical_issues:
            status = "需要整改"
        elif overall >= 80:
            status = "合格"
        elif overall >= 60:
            status = "需改进"
        else:
            status = "不合格"

        # 生成摘要
        summary_parts = []
        summary_parts.append(f"格式审核: {format_report.overall_score:.0%} ({format_report.total_issues}个问题)")
        summary_parts.append(f"内容审核: {content_report.overall_score:.0%} (章节覆盖{content_report.section_coverage:.0%})")

        if ai_report and ai_report.available:
            summary_parts.append(f"AI分析: {ai_report.overall_score}/10分")
        elif ai_report and ai_report.error_message:
            summary_parts.append(f"AI分析: 不可用 ({ai_report.error_message})")
        else:
            summary_parts.append("AI分析: 未执行")

        return ReviewReport(
            filename=filename,
            department=department,
            review_timestamp=now,
            format_report=format_report,
            content_report=content_report,
            ai_report=ai_report.model_dump() if ai_report else AIReport(),
            overall_score=min(100.0, round(overall, 1)),
            status=status,
            summary="; ".join(summary_parts),
        )
