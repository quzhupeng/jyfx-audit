"""经营分析会资料审核工具 — Streamlit 前端入口 (暖色商务风)."""

from __future__ import annotations

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

# ---- 加载自定义 CSS ----
CSS_PATH = Path(__file__).parent / "static" / "style.css"
if CSS_PATH.exists():
    with open(CSS_PATH, encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# 确保 Streamlit 环境下 API Key 生效
if not settings.DEEPSEEK_API_KEY:
    try:
        _key = st.secrets.get("DEEPSEEK_API_KEY", "")
        if _key:
            settings.DEEPSEEK_API_KEY = _key
            settings.AI_ENABLED = True
    except Exception:
        pass

st.set_page_config(
    page_title="经营分析会资料审核",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---- 部门中文映射 ----
DEPT_LABELS = {
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
}

# ================================================================
# 侧边栏
# ================================================================
with st.sidebar:
    st.header("审核设置")

    departments = loader.list_business_contexts()
    if not departments:
        departments = ["default"]
    department = st.selectbox(
        "选择事业部",
        departments,
        format_func=lambda x: DEPT_LABELS.get(x, x),
    )

    # 业务上下文
    if department != "default":
        ctx = loader.load_business_context(department)
        if ctx.business_thread:
            with st.expander("业务主脉络"):
                st.write(ctx.business_thread)
        if ctx.focus_areas:
            with st.expander("核心指标"):
                for fa in ctx.focus_areas:
                    st.markdown(f"**{fa.area}**")
                    for kpi in fa.kpis:
                        st.caption(f"  - {kpi.name}")
                    st.write("")

    st.divider()

    # AI 开关
    ai_available = bool(settings.DEEPSEEK_API_KEY) or bool(settings.ANTHROPIC_API_KEY)
    if "ai_enabled" not in st.session_state:
        st.session_state.ai_enabled = ai_available
    ai_enabled = st.checkbox(
        "启用 AI 分析",
        disabled=not ai_available,
        help="需配置 DEEPSEEK_API_KEY 或 ANTHROPIC_API_KEY",
        key="ai_enabled",
    )
    if not ai_available:
        st.caption("未检测到 API Key，请在 .env 或 .streamlit/secrets.toml 设置 DEEPSEEK_API_KEY")

    st.divider()
    st.caption(
        f"支持格式：PDF\n最大文件大小：{settings.UPLOAD_MAX_SIZE_MB}MB"
    )


# ================================================================
# 主内容区
# ================================================================
st.title("经营分析会资料审核")
st.caption("上传经营分析汇报材料，系统自动进行格式检查、内容审核和 AI 深度分析")

# ---- 区域1：上传区 ----
col_upload, col_info = st.columns([2, 1])

with col_upload:
    uploaded_file = st.file_uploader(
        "上传经营分析汇报材料 (PDF)",
        type=["pdf"],
        help="请将 PPT/PPTX 导出为 PDF 后上传",
        label_visibility="collapsed",
    )

with col_info:
    # 部门信息卡片
    dept_label = DEPT_LABELS.get(department, department)
    if department != "default":
        ctx = loader.load_business_context(department)
        st.markdown(
            f'<div class="audit-card">'
            f'<div style="font-size:0.8rem;color:#8C7E6F;margin-bottom:0.3rem;">当前事业部</div>'
            f'<div style="font-size:1.2rem;font-weight:700;color:#3D3229;">{dept_label}</div>'
            f'<div style="margin-top:0.6rem;font-size:0.8rem;color:#8C7E6F;line-height:1.5;">'
            f'{(ctx.business_thread or "")[:120]}{"..." if ctx.business_thread and len(ctx.business_thread) > 120 else ""}'
            f'</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="audit-card">'
            '<div style="font-size:0.8rem;color:#8C7E6F;margin-bottom:0.3rem;">当前事业部</div>'
            '<div style="font-size:1.2rem;font-weight:700;color:#3D3229;">请选择事业部</div>'
            '</div>',
            unsafe_allow_html=True,
        )

# ---- 区域2：审核按钮 ----
st.markdown("---")
btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 3])

with btn_col1:
    can_review = uploaded_file is not None
    start_review = st.button("开始审核", disabled=not can_review, type="primary", use_container_width=True)

with btn_col2:
    # AI 分析按钮 — 仅在基础审核完成且有 AI 可用时显示
    has_review = "review_result" in st.session_state and st.session_state.review_result is not None
    ai_report_done = has_review and st.session_state.review_result.get("ai_report") is not None
    ai_btn_disabled = not (has_review and ai_enabled and not ai_report_done)
    ai_label = "AI 分析中..." if (has_review and ai_report_done) else "启动 AI 深度分析"
    run_ai = st.button(ai_label, disabled=ai_btn_disabled, type="secondary", use_container_width=True)

# ---- 无文件时的占位提示 ----
if not can_review:
    st.info("请先上传 PDF 文件，然后点击「开始审核」")
    st.stop()

# ================================================================
# 基础审核流程（格式 + 内容）
# ================================================================
if start_review:
    with st.spinner("正在审核中..."):
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name

        # 解析 PDF
        with st.status("解析 PDF 文件...", expanded=False) as status:
            try:
                doc = parse_pdf(file_bytes, filename)
                stats = get_document_stats(doc)
                status.update(label=f"PDF 解析完成 — {doc.page_count}页, {stats['text_spans']}个文字片段", state="complete")
            except Exception as e:
                st.error(f"PDF 解析失败: {e}")
                st.stop()

        # 加载模板
        template = loader.load_template()

        # 章节匹配
        section_map = match_all_chapters_flexible(doc, template)
        matched_count = section_map.matched_count
        total_count = section_map.total_count

        # 格式检查
        format_checker = FormatChecker(template)
        format_report = format_checker.check(doc, section_map)

        # 内容检查
        content_checker = ContentChecker(template)
        content_report = content_checker.check(doc, section_map)

        # 生成初步报告（不含 AI）
        generator = ReportGenerator(template)
        report = generator.merge(
            filename=filename,
            department=department,
            format_report=format_report,
            content_report=content_report,
            ai_report=None,
        )

        # 缓存到 session_state
        st.session_state.review_result = {
            "doc": doc,
            "stats": stats,
            "template": template,
            "section_map": section_map,
            "format_report": format_report,
            "content_report": content_report,
            "ai_report": None,
            "report": report,
        }

# ================================================================
# AI 深度分析流程（手动触发）
# ================================================================
if run_ai and has_review:
    rv = st.session_state.review_result
    with st.spinner("AI 深度分析中，请稍候..."):
        business_ctx = loader.load_business_context(department) if department != "default" else None
        ai_report = analyze_content(rv["doc"], rv["section_map"], business_ctx)

        # 重新生成综合报告（含 AI）
        generator = ReportGenerator(rv["template"])
        report = generator.merge(
            filename=rv["report"].filename,
            department=department,
            format_report=rv["format_report"],
            content_report=rv["content_report"],
            ai_report=ai_report,
        )

        # 更新 session_state
        st.session_state.review_result["ai_report"] = ai_report
        st.session_state.review_result["report"] = report

# ================================================================
# 结果展示区
# ================================================================
has_review = "review_result" in st.session_state and st.session_state.review_result is not None
if not has_review:
    st.stop()

rv = st.session_state.review_result
report = rv["report"]
format_report = rv["format_report"]
content_report = rv["content_report"]
ai_report = rv["ai_report"]
section_map = rv["section_map"]
doc = rv["doc"]
stats = rv["stats"]

st.markdown("---")

# ---- 顶部：综合评分 + 状态 ----
status_color_map = {
    "合格": ("status-pass", "#6AAF5C"),
    "需改进": ("status-warn", "#E8A13A"),
    "需要整改": ("status-fail", "#D4544E"),
    "不合格": ("status-fail", "#D4544E"),
}
status_class, status_hex = status_color_map.get(report.status, ("status-warn", "#8C7E6F"))

col_hero1, col_hero2, col_hero3 = st.columns([1, 1, 1])

with col_hero1:
    st.markdown(
        f'<div class="score-hero">'
        f'<div class="score-value">{report.overall_score:.0f}</div>'
        f'<div class="score-label">综合评分 / 100</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

with col_hero2:
    st.markdown(
        f'<div class="audit-card" style="text-align:center;">'
        f'<div style="font-size:0.85rem;color:#8C7E6F;margin-bottom:0.5rem;">审核状态</div>'
        f'<div style="font-size:1.4rem;font-weight:700;margin-bottom:0.5rem;">'
        f'<span class="status-badge {status_class}">{report.status}</span></div>'
        f'<div style="font-size:0.78rem;color:#8C7E6F;margin-top:0.8rem;line-height:1.5;">'
        f'{report.summary}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

with col_hero3:
    ai_score_display = "未分析"
    ai_score_color = "#8C7E6F"
    if ai_report and ai_report.available:
        ai_score_display = f"{ai_report.overall_score}/10"
        ai_score_color = "#5A9BD5"
    st.markdown(
        f'<div class="audit-card" style="text-align:center;">'
        f'<div style="font-size:0.85rem;color:#8C7E6F;margin-bottom:0.5rem;">AI 深度分析</div>'
        f'<div style="font-size:1.6rem;font-weight:700;color:{ai_score_color};">{ai_score_display}</div>'
        f'<div style="font-size:0.75rem;color:#8C7E6F;margin-top:0.5rem;">'
        f'{"点击上方按钮启动分析" if not ai_report else ("分析完成" if ai_report.available else ai_report.error_message)}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

# ---- 中部：三列指标卡 ----
col_m1, col_m2, col_m3 = st.columns(3)

with col_m1:
    fmt_pct = format_report.overall_score * 100
    fmt_color = "#6AAF5C" if fmt_pct >= 80 else "#E8A13A" if fmt_pct >= 60 else "#D4544E"
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="metric-value" style="color:{fmt_color};">{fmt_pct:.0f}<span style="font-size:0.9rem;">%</span></div>'
        f'<div class="metric-label">格式评分</div>'
        f'<div style="margin-top:0.5rem;">'
        f'<div class="score-bar-bg"><div class="score-bar-fill" style="width:{fmt_pct}%;background:{fmt_color};"></div></div>'
        f'</div>'
        f'<div style="font-size:0.75rem;color:#8C7E6F;margin-top:0.4rem;">{format_report.total_issues} 个问题</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

with col_m2:
    cnt_pct = content_report.overall_score * 100
    cnt_color = "#6AAF5C" if cnt_pct >= 80 else "#E8A13A" if cnt_pct >= 60 else "#D4544E"
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="metric-value" style="color:{cnt_color};">{cnt_pct:.0f}<span style="font-size:0.9rem;">%</span></div>'
        f'<div class="metric-label">内容评分</div>'
        f'<div style="margin-top:0.5rem;">'
        f'<div class="score-bar-bg"><div class="score-bar-fill" style="width:{cnt_pct}%;background:{cnt_color};"></div></div>'
        f'</div>'
        f'<div style="font-size:0.75rem;color:#8C7E6F;margin-top:0.4rem;">覆盖 {content_report.section_coverage:.0%}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

with col_m3:
    if ai_report and ai_report.available:
        ai_pct = ai_report.overall_score / 10 * 100
        ai_color = "#6AAF5C" if ai_pct >= 80 else "#E8A13A" if ai_pct >= 60 else "#D4544E"
        st.markdown(
            f'<div class="metric-card">'
            f'<div class="metric-value" style="color:{ai_color};">{ai_report.overall_score}<span style="font-size:0.9rem;">/10</span></div>'
            f'<div class="metric-label">AI 综合评分</div>'
            f'<div style="margin-top:0.5rem;">'
            f'<div class="score-bar-bg"><div class="score-bar-fill" style="width:{ai_pct}%;background:{ai_color};"></div></div>'
            f'</div>'
            f'<div style="font-size:0.75rem;color:#8C7E6F;margin-top:0.4rem;">{len(ai_report.dimensions)} 个维度</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="metric-card">'
            '<div class="metric-value" style="color:#8C7E6F;">--</div>'
            '<div class="metric-label">AI 综合评分</div>'
            '<div style="font-size:0.75rem;color:#8C7E6F;margin-top:0.4rem;">尚未分析</div>'
            '</div>',
            unsafe_allow_html=True,
        )

# ---- 底部：标签页详情 ----
tab1, tab2, tab3, tab4 = st.tabs([
    "格式审核",
    "内容审核",
    "AI 分析",
    "文档信息",
])

# ---- Tab 1: 格式审核 ----
with tab1:
    st.subheader(f"格式审核 — {format_report.overall_score:.0%}")
    st.metric("问题总数", format_report.total_issues)

    if format_report.total_issues == 0:
        st.success("未发现格式问题！")

    for category, label in [("font", "字体"), ("size", "字号"), ("color", "颜色"), ("layout", "排版"), ("margin", "页边距")]:
        cat_issues = [i for i in format_report.issues if i.category == category]
        if not cat_issues:
            continue
        with st.expander(f"{label} — {len(cat_issues)}个问题"):
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

# ---- Tab 2: 内容审核 ----
with tab2:
    st.subheader(f"内容审核 — {content_report.overall_score:.0%}")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("章节覆盖", f"{content_report.section_coverage:.0%}")
    with c2:
        st.metric("核心章节完整", "✅" if content_report.essential_complete else "❌")
    with c3:
        st.metric("章节顺序", "✅" if content_report.order_correct else "❌")

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

# ---- Tab 3: AI 分析 ----
with tab3:
    st.subheader("AI 内容分析")

    if ai_report and ai_report.available:
        st.metric("AI 综合评分", f"{ai_report.overall_score}/10")

        if ai_report.summary:
            st.markdown(f"> {ai_report.summary}")

        if ai_report.dimensions:
            st.subheader("维度评分")
            for dim in ai_report.dimensions:
                dim_pct = dim.score / 10 * 100
                dim_color = "#6AAF5C" if dim_pct >= 80 else "#E8A13A" if dim_pct >= 60 else "#D4544E"
                st.markdown(
                    f'<div class="audit-card" style="margin-bottom:0.8rem;">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;">'
                    f'<span style="font-weight:600;">{dim.name}</span>'
                    f'<span style="font-weight:700;color:{dim_color};">{dim.score}/10</span>'
                    f'</div>'
                    f'<div style="margin:0.4rem 0;">'
                    f'<div class="score-bar-bg"><div class="score-bar-fill" style="width:{dim_pct}%;background:{dim_color};"></div></div>'
                    f'</div>'
                    f'<div style="font-size:0.85rem;color:#3D3229;margin-top:0.3rem;">{dim.comment}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if dim.suggestions:
                    for sug in dim.suggestions:
                        st.markdown(f"  - {sug}")

        if ai_report.risk_warnings:
            st.subheader("风险提示")
            for risk in ai_report.risk_warnings:
                st.warning(risk)

    elif ai_report and ai_report.error_message:
        st.warning(f"AI 分析不可用: {ai_report.error_message}")
    else:
        st.info("AI 分析未执行。点击上方「启动 AI 深度分析」按钮开始分析。")

# ---- Tab 4: 文档信息 ----
with tab4:
    st.subheader("文档统计信息")

    d1, d2, d3, d4 = st.columns(4)
    with d1:
        st.metric("文件名", doc.filename)
    with d2:
        st.metric("总页数", doc.page_count)
    with d3:
        st.metric("文字片段", f"{stats['text_spans']}个")
    with d4:
        st.metric("图片/图表", f"{stats['images']}个")

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

    st.subheader("章节页数分布")
    for ch in section_map.sections:
        if ch.matched and ch.segment_info:
            pct = ch.segment_info.page_count / doc.page_count * 100
            st.progress(min(pct / 100, 1.0), text=f"{ch.section_name}: {ch.segment_info.page_count}页 ({pct:.0f}%)")

    with st.expander("查看原始审核数据"):
        st.json(report.to_dict())
