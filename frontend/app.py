"""经营分析会资料审核工具 — Streamlit 前端入口."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

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

# ---- Load custom CSS ----
CSS_PATH = Path(__file__).parent / "static" / "style.css"
if CSS_PATH.exists():
    with open(CSS_PATH, encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Load API key from Streamlit secrets
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
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

DEPT_LABELS = {
    "direct_sales": "直销事业部", "beauty": "美业事业部",
    "digital_marketing": "数字营销", "finance": "财务部",
    "lingshen": "领参", "audit": "纪审部",
    "raw_materials": "原材料事业部", "private_domain": "私域事业部",
    "management_center": "管理中心", "rd_center": "研发中心",
    "stem_cell": "干细胞研究院", "foreign_trade": "外贸事业部",
    "production": "生产中心", "default": "默认（未配置）",
}

# ================================================================
# Sidebar
# ================================================================
with st.sidebar:
    st.header("审核设置")

    departments = loader.list_business_contexts()
    if not departments:
        departments = ["default"]
    department = st.selectbox(
        "选择事业部", departments,
        format_func=lambda x: DEPT_LABELS.get(x, x),
    )

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
        st.caption("未检测到 API Key，请在 .env 或 .streamlit/secrets.toml 设置")

    st.divider()
    st.caption(f"支持格式：PDF | 最大 {settings.UPLOAD_MAX_SIZE_MB}MB")


# ================================================================
# Main Content
# ================================================================
st.title("经营分析会资料审核")

col_upload, col_info = st.columns([2.2, 1])

with col_upload:
    uploaded_file = st.file_uploader(
        "上传经营分析汇报材料 (PDF)",
        type=["pdf"],
        help="请将 PPT/PPTX 导出为 PDF 后上传",
        label_visibility="collapsed",
    )

with col_info:
    dept_label = DEPT_LABELS.get(department, department)
    if department != "default":
        ctx = loader.load_business_context(department)
        thread_preview = (ctx.business_thread or "")[:120]
        st.markdown(
            f'<div class="dept-card">'
            f'<div class="dc-label">当前事业部</div>'
            f'<div class="dc-name">{dept_label}</div>'
            f'<div class="dc-thread">{thread_preview}{"..." if ctx.business_thread and len(ctx.business_thread) > 120 else ""}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="dept-card">'
            '<div class="dc-label">当前事业部</div>'
            '<div class="dc-name">请选择事业部</div>'
            '</div>',
            unsafe_allow_html=True,
        )

# ---- Review button ----
can_review = uploaded_file is not None
start_review = st.button("开始审核", disabled=not can_review, type="primary")

if not can_review:
    st.info("上传 PDF 文件后点击「开始审核」")
    st.stop()

# ================================================================
# Basic Review (format + content)
# ================================================================
if start_review:
    with st.spinner("正在审核中..."):
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name

        with st.status("解析 PDF 文件...", expanded=False) as status:
            try:
                doc = parse_pdf(file_bytes, filename)
                stats = get_document_stats(doc)
                status.update(label=f"PDF 解析完成 — {doc.page_count}页, {stats['text_spans']}个文字片段", state="complete")
            except Exception as e:
                st.error(f"PDF 解析失败: {e}")
                st.stop()

        template = loader.load_template()
        section_map = match_all_chapters_flexible(doc, template)

        format_checker = FormatChecker(template)
        format_report = format_checker.check(doc, section_map)

        content_checker = ContentChecker(template)
        content_report = content_checker.check(doc, section_map)

        generator = ReportGenerator(template)
        report = generator.merge(
            filename=filename, department=department,
            format_report=format_report, content_report=content_report,
            ai_report=None,
        )
        st.session_state.review_result = {
            "doc": doc, "stats": stats, "template": template,
            "section_map": section_map, "format_report": format_report,
            "content_report": content_report, "ai_report": None, "report": report,
        }
    st.rerun()

# ================================================================
# AI Button — only after review completes
# ================================================================
has_review = "review_result" in st.session_state and st.session_state.review_result is not None
run_ai = False

if has_review:
    ai_report_done = st.session_state.review_result.get("ai_report") is not None
    ai_btn_disabled = not (ai_enabled and not ai_report_done)
    run_ai = st.button("启动 AI 深度分析", disabled=ai_btn_disabled, type="secondary")

# ================================================================
# AI Analysis
# ================================================================
if run_ai and has_review:
    rv = st.session_state.review_result
    with st.spinner("AI 深度分析中，请稍候..."):
        business_ctx = loader.load_business_context(department) if department != "default" else None
        ai_report = analyze_content(rv["doc"], rv["section_map"], business_ctx)
        generator = ReportGenerator(rv["template"])
        report = generator.merge(
            filename=rv["report"].filename, department=department,
            format_report=rv["format_report"], content_report=rv["content_report"],
            ai_report=ai_report,
        )
        st.session_state.review_result["ai_report"] = ai_report
        st.session_state.review_result["report"] = report

# ================================================================
# Results
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

# ---- Hero: Score + Status + AI ----
status_color_map = {
    "合格": ("status-pass", "#5A9E50"),
    "需改进": ("status-warn", "#CC8B2E"),
    "需要整改": ("status-fail", "#C0443E"),
    "不合格": ("status-fail", "#C0443E"),
}
status_class, status_hex = status_color_map.get(report.status, ("status-warn", "#9B8E80"))

col_hero, col_ai = st.columns([2, 1])

with col_hero:
    st.markdown(
        f'<div class="score-hero">'
        f'<div class="score-value">{report.overall_score:.0f}</div>'
        f'<div class="score-divider"></div>'
        f'<div class="score-status-wrap">'
        f'<div style="font-size:0.72rem;opacity:0.5;text-transform:uppercase;letter-spacing:0.05em;font-weight:500;">综合评分</div>'
        f'<div style="margin-top:0.3rem;"><span class="status-badge {status_class}">{report.status}</span></div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

with col_ai:
    ai_val = "--"
    ai_color = "#9B8E80"
    ai_hint = "点击上方按钮启动分析"
    if ai_report and ai_report.available:
        ai_val = f"{ai_report.overall_score}/10"
        ai_color = "#4889B8"
        ai_hint = "分析完成"
    elif ai_report and ai_report.error_message:
        ai_hint = ai_report.error_message[:50]
    st.markdown(
        f'<div class="ai-status-card">'
        f'<div class="ai-val" style="color:{ai_color};">{ai_val}</div>'
        f'<div class="ai-label">AI 深度分析</div>'
        f'<div class="ai-hint">{ai_hint}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

# ---- Metric Strip ----
fmt_pct = format_report.overall_score * 100
cnt_pct = content_report.overall_score * 100
fmt_color = "#5A9E50" if fmt_pct >= 80 else "#CC8B2E" if fmt_pct >= 60 else "#C0443E"
cnt_color = "#5A9E50" if cnt_pct >= 80 else "#CC8B2E" if cnt_pct >= 60 else "#C0443E"

if ai_report and ai_report.available:
    ai_pct = ai_report.overall_score / 10 * 100
    ai_color = "#5A9E50" if ai_pct >= 80 else "#CC8B2E" if ai_pct >= 60 else "#C0443E"
    ai_cell = (
        f'<div class="metric-cell">'
        f'<div class="mc-value" style="color:{ai_color};">{ai_report.overall_score}<span style="font-size:0.75rem;font-weight:400;">/10</span></div>'
        f'<div class="mc-label">AI 评分</div>'
        f'<div class="mc-bar-bg"><div class="mc-bar-fill" style="width:{ai_pct}%;background:{ai_color};"></div></div>'
        f'<div class="mc-sub">{len(ai_report.dimensions)} 个维度</div>'
        f'</div>'
    )
else:
    ai_cell = (
        '<div class="metric-cell">'
        '<div class="mc-value" style="color:#9B8E80;">--</div>'
        '<div class="mc-label">AI 评分</div>'
        '<div class="mc-sub">尚未分析</div>'
        '</div>'
    )

st.markdown(
    f'<div class="metric-strip">'
    f'<div class="metric-cell">'
    f'<div class="mc-value" style="color:{fmt_color};">{fmt_pct:.0f}<span style="font-size:0.75rem;font-weight:400;">%</span></div>'
    f'<div class="mc-label">格式评分</div>'
    f'<div class="mc-bar-bg"><div class="mc-bar-fill" style="width:{fmt_pct}%;background:{fmt_color};"></div></div>'
    f'<div class="mc-sub">{format_report.total_issues} 个问题</div>'
    f'</div>'
    f'<div class="metric-cell">'
    f'<div class="mc-value" style="color:{cnt_color};">{cnt_pct:.0f}<span style="font-size:0.75rem;font-weight:400;">%</span></div>'
    f'<div class="mc-label">内容评分</div>'
    f'<div class="mc-bar-bg"><div class="mc-bar-fill" style="width:{cnt_pct}%;background:{cnt_color};"></div></div>'
    f'<div class="mc-sub">章节覆盖 {content_report.section_coverage:.0%}</div>'
    f'</div>'
    f'{ai_cell}'
    f'</div>',
    unsafe_allow_html=True,
)

# ---- Tabs ----
tab1, tab2, tab3, tab4 = st.tabs(["格式审核", "内容审核", "AI 分析", "文档信息"])

# ---- Tab 1: Format Review ----
with tab1:
    fmt_pct = format_report.overall_score * 100
    fmt_color = "#5A9E50" if fmt_pct >= 80 else "#CC8B2E" if fmt_pct >= 60 else "#C0443E"
    st.markdown(
        f'<div class="tab-section-title">格式审核 &mdash; {fmt_pct:.0f}% &nbsp;({format_report.total_issues} 个问题)</div>',
        unsafe_allow_html=True,
    )
    if format_report.total_issues == 0:
        st.success("未发现格式问题！")

    for category, label in [("font", "字体"), ("size", "字号"), ("color", "颜色"), ("layout", "排版"), ("margin", "页边距")]:
        cat_issues = [i for i in format_report.issues if i.category == category]
        if not cat_issues:
            continue
        issues_html = ""
        for issue in cat_issues:
            sev_dot = {"error": "red", "warning": "orange", "info": "blue"}.get(issue.severity, "gray")
            page_label = "文档级" if issue.page_number == 0 else f"第{issue.page_number}页"
            snippet = f'<div style="font-size:0.76rem;color:var(--c-muted);margin-top:0.15rem;font-style:italic;">{issue.text_snippet}</div>' if issue.text_snippet else ""
            issues_html += (
                f'<div class="issue-item severity-{issue.severity}">'
                f'<span class="issue-icon" style="color:{sev_dot};">&#9679;</span>'
                f'<div class="issue-content"><strong>{page_label}</strong> &mdash; {issue.message}{snippet}</div></div>'
            )
        with st.expander(f"{label} — {len(cat_issues)}个问题"):
            st.markdown(f'<div class="issue-list">{issues_html}</div>', unsafe_allow_html=True)

# ---- Tab 2: Content Review ----
with tab2:
    cnt_pct = content_report.overall_score * 100
    cnt_color = "#5A9E50" if cnt_pct >= 80 else "#CC8B2E" if cnt_pct >= 60 else "#C0443E"
    st.markdown(
        f'<div class="tab-section-title">内容审核 &mdash; {cnt_pct:.0f}%</div>',
        unsafe_allow_html=True,
    )

    cov_color = "#5A9E50" if content_report.section_coverage >= 0.8 else "#CC8B2E" if content_report.section_coverage >= 0.5 else "#C0443E"
    ess_icon = "&#10003;" if content_report.essential_complete else "&#10007;"
    ord_icon = "&#10003;" if content_report.order_correct else "&#10007;"
    st.markdown(
        f'<div class="stat-grid-3">'
        f'<div class="stat-item"><div class="stat-num" style="color:{cov_color};">{content_report.section_coverage:.0%}</div><div class="stat-desc">章节覆盖</div></div>'
        f'<div class="stat-item"><div class="stat-num">{ess_icon}</div><div class="stat-desc">核心章节</div></div>'
        f'<div class="stat-item"><div class="stat-num">{ord_icon}</div><div class="stat-desc">章节顺序</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="tab-section-title">章节检测</div>', unsafe_allow_html=True)
    chapters_html = ""
    for ch in section_map.sections:
        matched_cls = "matched" if ch.matched else "unmatched"
        icon = "&#10003;" if ch.matched else "&#10007;"
        conf_color = "#5A9E50" if ch.confidence > 0.7 else "#CC8B2E" if ch.confidence > 0.3 else "#C0443E"
        conf_pct = ch.confidence * 100
        meta_parts = [f"{len(ch.matched_keywords)}/{ch.total_keywords} kw", f"{conf_pct:.0f}%"]
        if ch.matched and ch.segment_info:
            meta_parts.append(f"{ch.segment_info.page_count}p {ch.segment_info.text_length}字")
        meta_str = " &middot; ".join(meta_parts)
        chapters_html += (
            f'<div class="chapter-row {matched_cls}">'
            f'<span class="chapter-icon">{icon}</span>'
            f'<span class="chapter-name">{ch.section_name}</span>'
            f'<div class="conf-bar"><div class="conf-fill" style="width:{conf_pct}%;background:{conf_color};"></div></div>'
            f'<span class="chapter-meta">{meta_str}</span>'
            f'</div>'
        )
    st.markdown(f'<div class="chapter-list">{chapters_html}</div>', unsafe_allow_html=True)

    if content_report.total_issues > 0:
        st.markdown(f'<div class="tab-section-title">内容问题 &mdash; {content_report.total_issues}个</div>', unsafe_allow_html=True)
        issues_html = ""
        for issue in content_report.issues:
            issues_html += (
                f'<div class="issue-item severity-{issue.severity}">'
                f'<span class="issue-icon">&#9679;</span>'
                f'<div class="issue-content"><span class="issue-tag {issue.severity}">{issue.severity}</span>{issue.message}</div></div>'
            )
        st.markdown(f'<div class="issue-list">{issues_html}</div>', unsafe_allow_html=True)
    else:
        st.success("未发现内容问题！")

# ---- Tab 3: AI Analysis ----
with tab3:
    if ai_report and ai_report.available:
        st.markdown(
            f'<div class="tab-section-title">AI 内容分析 &mdash; {ai_report.overall_score}/10</div>',
            unsafe_allow_html=True,
        )
        if ai_report.summary:
            st.markdown(f'<div class="summary-quote">{ai_report.summary}</div>', unsafe_allow_html=True)

        if ai_report.dimensions:
            st.markdown('<div class="tab-section-title">维度评分</div>', unsafe_allow_html=True)
            dims_html = ""
            for dim in ai_report.dimensions:
                dim_pct = dim.score / 10 * 100
                dim_color = "#5A9E50" if dim_pct >= 80 else "#CC8B2E" if dim_pct >= 60 else "#C0443E"
                sug_html = ""
                if dim.suggestions:
                    items = "".join(f"<li>{s}</li>" for s in dim.suggestions)
                    sug_html = f'<div class="dim-suggestions"><ul>{items}</ul></div>'
                dims_html += (
                    f'<div class="dim-card">'
                    f'<div class="dim-header">'
                    f'<span class="dim-name">{dim.name}</span>'
                    f'<span class="dim-score" style="color:{dim_color};">{dim.score}/10</span>'
                    f'</div>'
                    f'<div class="dim-bar-bg"><div class="dim-bar-fill" style="width:{dim_pct}%;background:{dim_color};"></div></div>'
                    f'<div class="dim-comment">{dim.comment}</div>'
                    f'{sug_html}'
                    f'</div>'
                )
            st.markdown(dims_html, unsafe_allow_html=True)

        if ai_report.risk_warnings:
            st.markdown('<div class="tab-section-title">风险提示</div>', unsafe_allow_html=True)
            for risk in ai_report.risk_warnings:
                st.warning(risk)

    elif ai_report and ai_report.error_message:
        st.warning(f"AI 分析不可用: {ai_report.error_message}")
    else:
        st.info("AI 分析未执行。点击上方「启动 AI 深度分析」按钮开始。")

# ---- Tab 4: Document Info ----
with tab4:
    st.markdown(
        f'<div class="doc-overview-card">'
        f'<div class="doc-filename-bar">'
        f'<span class="doc-fn-icon">&#128196;</span>'
        f'<span class="doc-fn-text">{doc.filename}</span>'
        f'</div>'
        f'<div class="doc-overview-item"><div class="doc-ov-value">{doc.page_count}</div><div class="doc-ov-label">总页数</div></div>'
        f'<div class="doc-overview-item"><div class="doc-ov-value">{stats["text_spans"]}</div><div class="doc-ov-label">文字片段</div></div>'
        f'<div class="doc-overview-item"><div class="doc-ov-value">{stats["images"]}</div><div class="doc-ov-label">图片/图表</div></div>'
        f'<div class="doc-overview-item"><div class="doc-ov-value">{section_map.matched_count}/{section_map.total_count}</div><div class="doc-ov-label">已匹配章节</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="tab-section-title">字号分布</div>', unsafe_allow_html=True)
    size_data = {}
    for s in stats["font_sizes"]:
        pt = int(s)
        if pt >= 22: cat, cat_cls = "标题", "title"
        elif pt >= 14: cat, cat_cls = "小标题", "subtitle"
        elif pt >= 10: cat, cat_cls = "正文", "body"
        else: cat, cat_cls = "注释", "note"
        key = f"{pt}pt"
        if key not in size_data:
            size_data[key] = {"pt": pt, "count": 0, "cat": cat, "cat_cls": cat_cls}
        size_data[key]["count"] += 1
    max_count = max((d["count"] for d in size_data.values()), default=1)
    size_rows_html = ""
    for key in sorted(size_data.keys(), key=lambda k: size_data[k]["pt"], reverse=True):
        d = size_data[key]
        bar_w = (d["count"] / max_count) * 100 if max_count > 0 else 0
        size_rows_html += (
            f'<div class="size-row">'
            f'<span class="size-label">{d["pt"]}pt <span class="size-cat {d["cat_cls"]}">{d["cat"]}</span></span>'
            f'<span class="size-count">{d["count"]}</span>'
            f'<div class="size-bar-wrap"><div class="size-bar-inner" style="width:{bar_w}%;"></div></div>'
            f'</div>'
        )
    st.markdown(f'<div class="size-table">{size_rows_html}</div>', unsafe_allow_html=True)

    matched_sections = [ch for ch in section_map.sections if ch.matched and ch.segment_info]
    if matched_sections:
        st.markdown('<div class="tab-section-title">章节页数分布</div>', unsafe_allow_html=True)
        bars_html = ""
        max_pages = max(ch.segment_info.page_count for ch in matched_sections)
        for ch in matched_sections:
            pct = ch.segment_info.page_count / doc.page_count * 100
            bar_width = (ch.segment_info.page_count / max_pages) * 100 if max_pages > 0 else 0
            bars_html += (
                f'<div class="section-bar-row">'
                f'<span class="section-bar-label">{ch.section_name}</span>'
                f'<div class="section-bar-track">'
                f'<div class="section-bar-value" style="width:{bar_width}%;"><span>{ch.segment_info.page_count}页 {pct:.0f}%</span></div>'
                f'</div></div>'
            )
        st.markdown(f'<div class="section-bar-group">{bars_html}</div>', unsafe_allow_html=True)

    with st.expander("查看原始审核数据"):
        st.json(report.to_dict())
