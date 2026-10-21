"""
Generación de informe HTML para pipeline de leads.

Consume datos ya cargados en LeadsView:
- leads (lista filtrada o completa)
- funnel_stats (de get_funnel_stats)
- sources_data (de group_leads_by_source)
- marketing_summary (de get_marketing_efficiency_summary)
- marketing_metrics (de get_marketing_metrics)

NO realiza queries adicionales.
"""
import html
import os
from datetime import datetime
from .html_template import get_html_base
from .charts_generator import generate_pie_chart, generate_horizontal_bar_chart
from utils.formatting import format_datetime_us, format_eur
from domain.lead_stages import LEAD_STATUSES
from domain.source_labels import SOURCE_LABELS


# Source labels coherentes con tabla_leads.py
_SOURCE_LABELS = SOURCE_LABELS

_STATUS_LABELS = LEAD_STATUSES

_STATUS_BADGE_CLASS = {
    "new":       "badge-new",
    "contacted": "badge-contacted",
    "meeting":   "badge-meeting",
    "qualified": "badge-qualified",
    "nurture":   "badge-nurture",
    "converted": "badge-converted",
    "lost":      "badge-lost",
}

_FUNNEL_COLORS = {
    "leads":     "#39B54A",
    "meetings":  "#e65100",
    "converted": "#2e7d32",
}

_FUNNEL_TEXT_COLORS = {
    "leads":     "#176B2C",
    "meetings":  "#A33A00",
    "converted": "#176B2C",
}


def generate_leads_html_report(
    leads: list,
    funnel_stats: dict,
    sources_data: dict,
    filters_desc: str = "All leads",
    filename: str | None = None,
    marketing_summary: dict | None = None,
    marketing_metrics: list | None = None,
):
    """
    Genera un informe HTML del pipeline de leads.

    Args:
        leads: Lista de leads enriched (filtrados o totales)
        funnel_stats: dict de get_funnel_stats()
        sources_data: dict de group_leads_by_source()
        filters_desc: Descripción textual de los filtros activos
        filename: Ruta del archivo (si es None, genera uno automático)
        marketing_summary: dict de get_marketing_efficiency_summary() (opcional)
        marketing_metrics: list de get_marketing_metrics() (opcional)

    Returns:
        tuple (success: bool, message: str, filepath: str)
    """
    try:
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"Leads_Report_{timestamp}.html"

        if os.path.dirname(filename):
            os.makedirs(os.path.dirname(filename), exist_ok=True)

        # ── Funnel section ───────────────────────────────────────
        total = funnel_stats.get("total", 0)
        meetings = funnel_stats.get("meetings", 0)
        converted = funnel_stats.get("converted", 0)

        funnel_html = _render_funnel(total, meetings, converted)

        # ── KPI metrics ──────────────────────────────────────────
        lead_to_meeting_pct = funnel_stats.get("lead_to_meeting_pct", 0)
        meeting_to_client_pct = funnel_stats.get("meeting_to_client_pct", 0)
        avg_time = funnel_stats.get("avg_time_to_meeting", 0)

        kpi_html = f'''
        <div class="metrics">
            <div class="metric-card">
                <label>Total leads</label>
                <div class="value">{total}</div>
            </div>
            <div class="metric-card accent-orange">
                <label>Meetings</label>
                <div class="value">{meetings}</div>
            </div>
            <div class="metric-card accent-green">
                <label>Converted clients</label>
                <div class="value">{converted}</div>
            </div>
            <div class="metric-card accent-purple">
                <label>Lead &rarr; Meeting</label>
                <div class="value">{lead_to_meeting_pct:.1f}%</div>
            </div>
            <div class="metric-card accent-teal">
                <label>Meeting &rarr; Client</label>
                <div class="value">{meeting_to_client_pct:.1f}%</div>
            </div>
            <div class="metric-card accent-orange">
                <label>Average time to meeting</label>
                <div class="value">{avg_time:.0f} days</div>
            </div>
        </div>
        '''

        # ── Source distribution chart ────────────────────────────
        source_chart_html = ""
        if sources_data:
            src_labels = [_SOURCE_LABELS.get(s, s) for s in sources_data]
            src_values = [float(d["total"]) for d in sources_data.values()]

            try:
                pie_b64 = generate_pie_chart(src_labels, src_values)
                source_chart_html = f'''
                <div class="chart-container">
                    <h3>Distribution by source</h3>
                    <img src="data:image/png;base64,{pie_b64}"
                         alt="Lead distribution by source" style="width:100%;">
                </div>
                '''
            except Exception:
                pass

        # ── Source conversion table ───────────────────────────────
        source_table_html = ""
        if sources_data:
            rows_html = ""
            for src, data in sorted(sources_data.items(), key=lambda x: x[1]["total"], reverse=True):
                s_total = data["total"]
                s_meetings = data["meetings"]
                s_clients = data["clients"]
                s_conv = (s_clients / s_total * 100) if s_total else 0
                s_m2c = data.get("meeting_to_client_pct", 0)
                s_avg = data.get("avg_time_to_meeting", 0)
                rows_html += f'''<tr>
                    <td><strong>{html.escape(_SOURCE_LABELS.get(src, src))}</strong></td>
                    <td>{s_total}</td>
                    <td>{s_meetings}</td>
                    <td>{s_clients}</td>
                    <td>{s_conv:.1f}%</td>
                    <td>{s_m2c:.1f}%</td>
                    <td>{s_avg:.0f}d</td>
                </tr>
'''
            source_table_html = f'''
            <h2>Performance by source</h2>
            {source_chart_html}
            <table>
                <thead>
                    <tr>
                        <th>Source</th>
                        <th>Leads</th>
                        <th>Meetings</th>
                        <th>Clients</th>
                        <th>Total conv.</th>
                        <th>Meeting &rarr; Client</th>
                        <th>Avg. time to meeting</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
            '''

        # ── Leads table ──────────────────────────────────────────
        leads_table_html = ""
        if leads:
            rows_html = ""
            for ld in leads[:50]:  # Limitar a 50 leads en el export
                created = (ld.get("created_at") or "")[:10]
                source = html.escape(_SOURCE_LABELS.get(ld.get("source", ""), ld.get("source", "—")))
                status_raw = (ld.get("status") or "").lower().strip()
                status_label = html.escape(_STATUS_LABELS.get(status_raw, status_raw))
                badge_class = _STATUS_BADGE_CLASS.get(status_raw, "badge-new")
                meeting = (ld.get("meeting_date") or "")[:10] if ld.get("meeting_date") else "—"
                client_name = html.escape(ld.get("client_name") or "—")

                rows_html += f'''<tr>
                    <td>{created}</td>
                    <td>{source}</td>
                    <td><span class="badge {badge_class}">{status_label}</span></td>
                    <td>{meeting}</td>
                    <td>{client_name}</td>
                </tr>
'''

            count_note = f" (showing the first 50 of {len(leads)})" if len(leads) > 50 else ""
            leads_table_html = f'''
            <h2>Lead list{count_note}</h2>
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Source</th>
                        <th>Status</th>
                        <th>Meeting</th>
                        <th>Client</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
            '''

        # ── Marketing Performance section ─────────────────────
        marketing_html = ""
        if marketing_summary:
            total_spend = float(marketing_summary.get("total_spend", 0) or 0)
            has_spend = total_spend > 0
            overall_roi = marketing_summary.get("overall_roi", 0.0)
            roi_color = ("#2e7d32" if overall_roi >= 0 else "#c62828") if has_spend else "#62637A"
            roi_str = f"{overall_roi * 100:.1f}%" if has_spend else "—"
            cpl_str = format_eur(marketing_summary.get("avg_cpl", 0)) if has_spend else "—"
            cac_str = format_eur(marketing_summary.get("avg_cac", 0)) if has_spend else "—"

            marketing_html += f'''
            <h2>Marketing performance <span style="font-size:12px;color:#666;font-weight:400;">· reflects the active filters</span></h2>
            <div class="metrics">
                <div class="metric-card accent-orange">
                    <label>Total spend</label>
                    <div class="value">{format_eur(total_spend)}</div>
                </div>
                <div class="metric-card accent-green">
                    <label>Attributed revenue</label>
                    <div class="value">{format_eur(marketing_summary.get("total_revenue", 0))}</div>
                </div>
                <div class="metric-card">
                    <label>CPL (cost per lead)</label>
                    <div class="value">{cpl_str}</div>
                </div>
                <div class="metric-card accent-purple">
                    <label>CAC (cost per client)</label>
                    <div class="value">{cac_str}</div>
                </div>
                <div class="metric-card" style="color:{roi_color}">
                    <label>Overall ROI</label>
                    <div class="value" style="color:{roi_color}">{roi_str}</div>
                </div>
            </div>
            '''

        if marketing_metrics:
            mkt_rows = ""
            for m in marketing_metrics:
                src_label = html.escape(_SOURCE_LABELS.get(m["source"], m["source"]))
                spend = float(m.get("spend", 0) or 0)
                has_spend = spend > 0
                roi = m.get("roi", 0.0)
                roi_pct = roi * 100
                roi_color = ("#2e7d32" if roi >= 0 else "#c62828") if has_spend else "#62637A"
                cpl = format_eur(m.get("cpl", 0)) if has_spend else "—"
                cac = format_eur(m.get("cac", 0)) if has_spend else "—"
                roi_text = f"{roi_pct:.1f}%" if has_spend else "—"
                mkt_rows += f'''<tr>
                    <td><strong>{src_label}</strong></td>
                    <td>{m.get("leads", 0)}</td>
                    <td>{m.get("customers", 0)}</td>
                    <td>{format_eur(m.get("revenue", 0))}</td>
                    <td>{format_eur(spend)}</td>
                    <td>{cpl}</td>
                    <td>{cac}</td>
                    <td style="color:{roi_color};font-weight:600">{roi_text}</td>
                </tr>
'''
            marketing_html += f'''
            <h3>Details by source</h3>
            <table>
                <thead>
                    <tr>
                        <th>Source</th><th>Leads</th><th>Clients</th>
                        <th>Revenue</th><th>Spend</th>
                        <th>CPL</th><th>CAC</th><th>ROI</th>
                    </tr>
                </thead>
                <tbody>{mkt_rows}</tbody>
            </table>
            '''

        # ── Filters description ──────────────────────────────────
        filters_html = f'''
        <div class="period-filters">
            <div class="period-section">
                <span class="period-icon">📋</span>
                <span class="period-text">{html.escape(filters_desc)}</span>
            </div>
        </div>
        '''

        # ── Assemble content ─────────────────────────────────────
        content_block = f'''
        <div class="header">
            <div class="brand">Techset LeadGen</div>
            <h1>Leads Report</h1>
            <p>Generated on {format_datetime_us(datetime.now())}</p>
        </div>
        <div class="content">
            {filters_html}
            <h2>Conversion funnel</h2>
            {funnel_html}
            <h2>Pipeline metrics</h2>
            {kpi_html}
            {source_table_html}
            {marketing_html}
            {leads_table_html}
        </div>
        <div class="footer">
            <p><strong>Techset LeadGen</strong></p>
            <p>Report generated automatically by the lead management system.</p>
            <p>&copy; {datetime.now().year} Techset LeadGen.</p>
        </div>
        '''

        html_content = get_html_base(
            content_block,
            title="Techset LeadGen - Leads Report",
        )

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return (True, f"Report generated: {os.path.basename(filename)}", filename)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return (False, f"Could not generate the leads report: {str(e)}", None)


def _render_funnel(total: int, meetings: int, converted: int) -> str:
    """Renderiza embudo visual en HTML usando las clases CSS del template."""
    stages = [
        ("Leads", total, _FUNNEL_COLORS["leads"], _FUNNEL_TEXT_COLORS["leads"], 100),
        ("Meetings", meetings, _FUNNEL_COLORS["meetings"], _FUNNEL_TEXT_COLORS["meetings"],
         (meetings / total * 100) if total else 0),
        ("Clients", converted, _FUNNEL_COLORS["converted"], _FUNNEL_TEXT_COLORS["converted"],
         (converted / total * 100) if total else 0),
    ]

    html = ""
    for label, value, color, text_color, bar_pct in stages:
        pct_text = f"{bar_pct:.1f}%" if bar_pct < 100 else ""
        html += f'''
        <div class="funnel-stage">
            <div class="stage-bar" style="width: {max(bar_pct, 8)}%; background: {color};"></div>
            <span class="stage-label" style="color: {text_color};">{label}</span>
            <span class="stage-value" style="color: {text_color};">{value}</span>
            <span class="stage-pct">{pct_text}</span>
        </div>
        '''
    return html
