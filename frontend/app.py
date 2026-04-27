"""经营分析会资料审核工具 — Streamlit 前端入口."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import streamlit as st

# 确保项目根目录在 path 中
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import settings, loader
from services.pdf_parser import parse_pdf, get_document_stats
from services.template_engine import match_all_chapters_flexible
from services.format_checker import FormatChecker
from services.content_checker import ContentChecker
from services.ai_analyzer import analyze_content
from services.report_generator import ReportGenerator
from models.review import ReviewReport

st.set_page_config(
    page_title="经营分析会资料审核",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---- 侧边栏 ----
with st.sidebar:
    st.header("📋 审核设置")

    # 事业部选择
    departments = loader.list_business_contexts()
    if not departments:
        departments = ["default"]
    department = st.selectbox(
        "选择事业部",
        departments,
        format_func=lambda x: {
            "direct_sales": "直销事业部",
            "beauty": "美业事业部",
            "digital_marketing": "数字营销",
            "finance": "财务部",
            "lingshen": "领参",
            "audit": "纪审部",
            "raw_materials": "原材料事业部",
            "private_domain": "私域事业部",
            "management_center": "管理中心",
            "rd_center": "研发中心",
            "stem_cell": "干细胞研究院",
            "foreign_trade": "外贸事业部",
            "production": "生产中心",
            "default": "默认（未配置）",
        }.get(x, x),
    )

    # 显示业务主脉络和核心指标
    if department != "default":
        ctx = loader.load_business_context(department)
        if ctx.business_thread:
            with st.expander("🔗 业务主脉络"):
                st.write(ctx.business_thread)
        if ctx.focus_areas:
            with st.expander("📊 核心指标"):
                for fa in ctx.focus_areas:
                    st.markdown(f"**{fa.area}**")
                    for kpi in fa.kpis:
                        st.caption(f"  - {kpi.name}")
                    st.write("")

    st.divider()

    # AI 分析开关
    ai_available = bool(settings.DEEPSEEK_API_KEY) or bool(settings.ANTHROPIC_API_KEY)
    ai_enabled = st.checkbox(
        "启用 DeepSeek AI 分析",
        value=ai_available,
        disabled=not ai_available,
        help="需要配置 DEEPSEEK_API_KEY 环境变量",
    )
    if not ai_available:
        st.caption("💡 设置 DEEPSEEK_API_KEY 环境变量以启用 AI 分析")

    st.divider()
    st.caption(
        "支持格式：PDF\n"
        f"最大文件大小：{settings.UPLOAD_MAX_SIZE_MB}MB"
    )

# ---- 主内容区 ----
st.title("经营分析会资料审核")

# 上传区域
col1, col2 = st.columns([2, 1])
with col1:
    uploaded_file = st.file_uploader(
        "上传经营分析汇报材料 (PDF)",
        type=["pdf"],
        help="请将 PPT/PPTX 导出为 PDF 后上传",
    )

with col2:
    st.markdown("### 使用说明")
    st.markdown(
        """
        1. 将PPT汇报材料导出为PDF
        2. 选择对应的事业部
        3. 上传PDF文件
        4. 点击「开始审核」
        5. 查看各维度审核结果
        """
    )

# 审核按钮
can_review = uploaded_file is not None
start_review = st.button("🔍 开始审核", disabled=not can_review, type="primary")

if not start_review:
    st.info("👆 请先上传 PDF 文件，然后点击「开始审核」")
    st.stop()

# ---- 执行审核 ----
with st.spinner("正在审核中..."):
    file_bytes = uploaded_file.read()
    filename = uploaded_file.name

    # Step 1: 解析 PDF
    with st.status("📄 解析 PDF 文件...", expanded=False) as status:
        try:
            doc = parse_pdf(file_bytes, filename)
            stats = get_document_stats(doc)
            status.update(label=f"📄 PDF 解析完成 — {doc.page_count}页, {stats['text_spans']}个文字片段", state="complete")
        except Exception as e:
            st.error(f"PDF 解析失败: {e}")
            st.stop()

    # Step 2: 加载模板
    template = loader.load_template()
    st.success(f"📋 模板加载完成: {template.name} v{template.version} ({len(template.sections)}个章节)")

    # Step 3: 章节匹配（柔性匹配：基于标题边界检测）
    section_map = match_all_chapters_flexible(doc, template)
    matched_count = section_map.matched_count
    total_count = section_map.total_count
    st.success(f"🔍 章节匹配完成: {matched_count}/{total_count} 个章节被检测到")

    # Step 4: 格式检查
    format_checker = FormatChecker(template)
    format_report = format_checker.check(doc, section_map)
    st.success(f"✅ 格式检查完成: {format_report.total_issues}个问题")

    # Step 5: 内容检查
    content_checker = ContentChecker(template)
    content_report = content_checker.check(doc, section_map)
    st.success(f"📝 内容检查完成: {content_report.total_issues}个问题")

    # Step 6: AI 分析
    ai_report = None
    if ai_enabled:
        with st.spinner("🤖 AI 分析中..."):
            business_ctx = loader.load_business_context(department) if department != "default" else None
            ai_report = analyze_content(doc, section_map, business_ctx)
            if ai_report.available:
                st.success(f"🤖 AI 分析完成: {ai_report.overall_score}/10分")
            else:
                st.warning(f"🤖 AI 分析失败: {ai_report.error_message}")

    # Step 7: 生成综合报告
    generator = ReportGenerator(template)
    report = generator.merge(
        filename=filename,
        department=department,
        format_report=format_report,
        content_report=content_report,
        ai_report=ai_report,
    )

# ---- 展示结果 ----
st.divider()
st.header("审核结果")

# 综合评分卡片
col1, col2, col3, col4 = st.columns(4)
status_color = {
    "合格": "green",
    "需改进": "orange",
    "需要整改": "red",
    "不合格": "red",
}
with col1:
    st.metric("综合评分", f"{report.overall_score:.0f}/100")
with col2:
    color = status_color.get(report.status, "grey")
    st.markdown(f"### :{color}[{report.status}]")
with col3:
    st.metric("格式评分", f"{format_report.overall_score:.0%}")
with col4:
    st.metric("内容评分", f"{content_report.overall_score:.0%}")

st.caption(report.summary)

# Tab 展示各维度
tab1, tab2, tab3, tab4 = st.tabs([
    "📐 格式审核",
    "📝 内容审核",
    "🤖 AI 分析",
    "📊 文档信息",
])

# Tab 1: 格式审核
with tab1:
    st.subheader(f"格式审核 — {format_report.overall_score:.0%}")

    st.metric("问题总数", format_report.total_issues)

    if format_report.total_issues == 0:
        st.success("未发现格式问题！")

    # 按类别分组展示
    for category, label in [("font", "字体"), ("size", "字号"), ("color", "颜色"), ("layout", "排版"), ("margin", "页边距")]:
        cat_issues = [i for i in format_report.issues if i.category == category]
        if not cat_issues:
            continue

        with st.expander(f"🔤 {label} — {len(cat_issues)}个问题"):
            for issue in cat_issues:
                severity_icon = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(issue.severity, "⚪")
                page_label = "文档级" if issue.page_number == 0 else f"第{issue.page_number}页"
                st.markdown(
                    f"{severity_icon} **{page_label}**: {issue.message}\n\n"
                    f"> 文字片段: _{issue.text_snippet}_"
                )
                if issue.detail:
                    with st.expander("详情"):
                        st.json(issue.detail)

# Tab 2: 内容审核
with tab2:
    st.subheader(f"内容审核 — {content_report.overall_score:.0%}")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("章节覆盖", f"{content_report.section_coverage:.0%}")
    with col2:
        st.metric("核心章节完整", "✅" if content_report.essential_complete else "❌")
    with col3:
        st.metric("章节顺序", "✅" if content_report.order_correct else "❌")

    # 章节匹配详情
    st.subheader("章节检测")
    for ch in section_map.sections:
        icon = "✅" if ch.matched else "❌"
        conf_color = "green" if ch.confidence > 0.7 else "orange" if ch.confidence > 0.3 else "red"
        st.markdown(
            f"{icon} **{ch.section_name}** "
            f"— 置信度: :{conf_color}[{ch.confidence:.0%}] "
            f"({len(ch.matched_keywords)}/{ch.total_keywords} 关键字)"
        )
        if ch.matched:
            page_info = f"第{ch.page_start}-{ch.page_end}页"
            if ch.segment_info:
                page_info = f"第{ch.page_start}-{ch.page_end}页（共{ch.segment_info.page_count}页，{ch.segment_info.text_length}字）"
                if ch.segment_info.title_text:
                    page_info += f" | 标题: {ch.segment_info.title_text}"
            st.caption(f"   {page_info} | 关键字: {', '.join(ch.matched_keywords[:5])}")

    # 内容问题
    if content_report.total_issues > 0:
        st.subheader(f"内容问题 — {content_report.total_issues}个")
        for issue in content_report.issues:
            severity_icon = {
                "critical": "🔴",
                "error": "🟠",
                "warning": "🟡",
                "info": "🔵",
            }.get(issue.severity, "⚪")
            st.markdown(f"{severity_icon} [{issue.severity}] {issue.message}")
    else:
        st.success("未发现内容问题！")

# Tab 3: AI 分析
with tab3:
    st.subheader("AI 内容分析")

    if ai_report and ai_report.available:
        st.metric("AI 综合评分", f"{ai_report.overall_score}/10")

        if ai_report.summary:
            st.markdown(f"> {ai_report.summary}")

        # 各维度评分
        if ai_report.dimensions:
            st.subheader("维度评分")
            for dim in ai_report.dimensions:
                with st.expander(f"{dim.name} — {dim.score}/10"):
                    st.write(dim.comment)
                    if dim.suggestions:
                        st.markdown("**改进建议:**")
                        for sug in dim.suggestions:
                            st.markdown(f"- {sug}")

        # 风险提示
        if ai_report.risk_warnings:
            st.subheader("⚠️ 风险提示")
            for risk in ai_report.risk_warnings:
                st.warning(risk)

    elif ai_report and ai_report.error_message:
        st.warning(f"AI 分析不可用: {ai_report.error_message}")
    else:
        st.info("AI 分析未启用。请在侧边栏开启或在环境变量中设置 DEEPSEEK_API_KEY。")

# Tab 4: 文档信息
with tab4:
    st.subheader("文档统计信息")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("文件名", doc.filename)
    with col2:
        st.metric("总页数", doc.page_count)
    with col3:
        st.metric("文字片段", f"{stats['text_spans']}个")
    with col4:
        st.metric("图片/图表", f"{stats['images']}个")

    # 字号分布
    st.subheader("字号分布")
    size_counts = {}
    for s in stats["font_sizes"]:
        size_range = f"{int(s)}pt"
        if s >= 22:
            size_range += "（标题级）"
        elif s >= 14:
            size_range += "（小标题）"
        elif s >= 10:
            size_range += "（正文）"
        else:
            size_range += "（注释/表格）"
        size_counts[size_range] = size_counts.get(size_range, 0) + 1
    for label, count in sorted(size_counts.items()):
        st.caption(f"  {label}: {count}种字号")

    # 章节页数分布
    st.subheader("章节页数分布")
    for ch in section_map.sections:
        if ch.matched and ch.segment_info:
            pct = ch.segment_info.page_count / doc.page_count * 100
            st.progress(min(pct / 100, 1.0), text=f"{ch.section_name}: {ch.segment_info.page_count}页 ({pct:.0f}%)")

    # 详细报告（折叠）
    with st.expander("查看原始审核数据"):
        st.json(report.to_dict())
