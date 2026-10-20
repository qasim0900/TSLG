"""
Generación de reportes en formato HTML.
"""
from datetime import datetime
from html import escape
import os
from .html_sections import render_period_filters, render_metrics, render_charts_section, render_chart_container
from .html_template import get_html_base
from .charts_generator import generate_evolution_line_chart, generate_compare_bar_chart, generate_evolution_bar_chart
from domain.analysis_snapshot import AnalysisSnapshot
from utils.formatting import format_datetime_us, format_eur_no_symbol, format_eur_signed


def generate_html_report_from_snapshot(snapshot: AnalysisSnapshot, filename=None):
    """
    Genera un informe HTML directamente desde un AnalysisSnapshot.
    
    Esta función NO hace queries ni recalcula métricas.
    Consume EXACTAMENTE lo que está en el snapshot.
    
    Soporta AMBOS modos:
    - Modo normal: Renderiza solo período A
    - Modo compare: Renderiza período A, período B y comparativa
    
    Args:
        snapshot: AnalysisSnapshot válido (ya validado)
        filename: Ruta del archivo (si es None, genera uno automático)
    
    Returns:
        tuple (success: bool, message: str, filepath: str)
    """
    
    try:
        # Validar snapshot
        if not snapshot.validate():
            return (False, "The analysis snapshot is invalid or inconsistent", None)
        
        # Generar nombre de archivo si no se proporciona
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            mode_suffix = "Compare" if snapshot.is_compare_mode() else "Normal"
            filename = f"Sales_Report_{mode_suffix}_{timestamp}.html"
        
        # Asegurar que el directorio existe
        if os.path.dirname(filename):
            os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        # ============================================================
        # Renderizar PERÍODO A
        # ============================================================
        
        period_a_html = _render_period_section(
            period=snapshot.period_a,
            section_title="Main period",
            is_comparison=False
        )
        
        # ============================================================
        # Renderizar PERÍODO B (solo si modo compare)
        # ============================================================
        
        period_b_html = ""
        if snapshot.is_compare_mode() and snapshot.period_b:
            period_b_html = _render_period_section(
                period=snapshot.period_b,
                section_title="Comparison period",
                is_comparison=False
            )
        
        # ============================================================
        # Renderizar COMPARATIVA (solo si modo compare)
        # ============================================================
        
        comparison_html = ""
        if snapshot.is_compare_mode() and snapshot.comparison:
            comparison_html = _render_comparison_section(
                comparison=snapshot.comparison,
                period_a=snapshot.period_a,
                period_b=snapshot.period_b,
            )
        
        # ============================================================
        # Construir bloque de contenido principal
        # ============================================================
        
        mode_label = "Comparison" if snapshot.is_compare_mode() else "Standard analysis"
        content_block = f'''
        <div class="header">
            <div class="brand">Techset LeadGen</div>
            <h1>Sales Report - {mode_label}</h1>
            <p>Generated on {format_datetime_us(datetime.now())}</p>
        </div>
        <div class="content">
            {period_a_html}
            {period_b_html}
            {comparison_html}
        </div>
        <div class="footer">
            <p><strong>Techset LeadGen</strong></p>
            <p>Report generated automatically by the sales management system.</p>
            <p>© {datetime.now().year} Techset LeadGen.</p>
        </div>
        '''
        
        html_content = get_html_base(
            content_block,
            title=f"Techset LeadGen - Sales Report - {mode_label}",
        )
        
        # Escribir archivo
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return (True, f"Report generated: {os.path.basename(filename)}", filename)
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return (False, f"Could not generate the report: {str(e)}", None)


# ============================================================
#   HELPERS PRIVADOS
# ============================================================

def _render_period_section(period, section_title: str, is_comparison: bool = False):
    """
    Renderiza una sección completa de período (A o B).
    
    Args:
        period: PeriodSnapshot
        section_title: Título para mostrar (ej: "Período Principal")
        is_comparison: Si es True, no muestra tabla de productos (solo resumen)
    
    Returns:
        HTML string
    """
    
    # Construir filtros dict para render_period_filters
    filters_dict = {
        'start_date': period.filters.date_start,
        'end_date': period.filters.date_end,
        'client_name': period.filters.client_name,
        'product_type': period.filters.product_type,
    }
    
    period_filters_html = render_period_filters(filters_dict)
    
    # Renderizar métricas
    metrics = period.metrics
    metrics_html = render_metrics(
        total_ventas=metrics.total_sales,
        total_cantidad=metrics.transactions,
        promedio=metrics.avg_ticket,
        num_productos=len(period.table_data),
        unique_clients=metrics.unique_clients,
    )
    # ============================================================
    # Gráfico de evolución temporal (MODO NORMAL)
    # ===========================================================
    evolution_chart_html = ""
    
    if (
        period.evolution
        and getattr(period.evolution, "labels", None)
        and getattr(period.evolution, "values", None)
        and len(period.evolution.labels) == len(period.evolution.values)
        and len(period.evolution.labels) > 0
    ):
        try:
           evolution_base64 = generate_evolution_bar_chart(
                labels=period.evolution.labels,
                values=period.evolution.values,
            )

           evolution_chart_html = render_chart_container(
                title="Sales trend",
                image_base64=evolution_base64
            )
        except Exception as e:
            evolution_chart_html = f"<p>Could not build the trend chart: {escape(str(e))}</p>"

    # Renderizar gráficos (solo si hay datos en product_distribution)
    charts_html = ""
    if period.product_distribution.labels and period.product_distribution.values:
        # Convertir ProductDistribution a formato esperado por render_charts_section
        # render_charts_section espera: rows (lista de tuplas) y clients_stats (lista de dicts)
        
        # Para product_distribution, construimos rows
        product_rows = [
            (label, value, 0, 0, 0, 0)  # Solo product_type y total importan
            for label, value in zip(
                period.product_distribution.labels,
                period.product_distribution.values
            )
        ]
        
        # Para top_clients, convertimos ClientRank a dict
        clients_stats = [
            {
                'name': client.client_name,
                'total_amount': client.total_sales,
                'total_sales': client.transactions,
            }
            for client in period.top_clients
        ] if period.top_clients else None

        # Pasar percentages pre-calculados del snapshot
        charts_html = render_charts_section(
            product_rows,
            clients_stats,
            percentages=period.product_distribution.percentages
        )
    
    # Tabla de productos (solo si NO es sección de comparación)
    table_html = ""
    if not is_comparison and period.table_data:
        table_rows_html = ""
        for row in period.table_data:
            table_rows_html += f'''<tr>
                <td><strong>{escape(str(row.product_type))}</strong></td>
                <td>{row.quantity:,.0f}</td>
                <td>{format_eur_no_symbol(row.total_sales)}</td>
                <td>{format_eur_no_symbol(row.avg_price)}</td>
                <td>{format_eur_no_symbol(row.min_price)}</td>
                <td>{format_eur_no_symbol(row.max_price)}</td>
            </tr>
'''
        
        table_html = f'''
            <h2>Details by product - {section_title}</h2>
            <table>
                <thead>
                    <tr>
                        <th>Product</th>
                        <th>Quantity</th>
                        <th>Total (€)</th>
                        <th>Average (€)</th>
                        <th>Min. (€)</th>
                        <th>Max. (€)</th>
                    </tr>
                </thead>
                <tbody>
                {table_rows_html}
                </tbody>
            </table>
        '''
    return f'''
        <h2>{section_title}</h2>
        {period_filters_html}
        {metrics_html}
        {evolution_chart_html}
        {charts_html}
        {table_html}
    '''


def _render_comparison_section(comparison, period_a, period_b):
    """
    Renderiza la sección de comparación (SOLO en modo compare).
    
    Consume EvolutionComparisonV2 directamente sin transformación.
    
    Args:
        comparison: ComparisonSnapshot
        filters_a: Filtros del período A
        filters_b: Filtros del período B (opcional)
    
    Returns:
        HTML string
    """
    
    if not comparison:
        return ""
    
    # ============================================================
    # Gráfico de evolución temporal
    # ============================================================
    
    evolution_chart_html = ""
    if comparison.evolution and comparison.evolution.points:
        try:
            evolution_base64 = generate_evolution_line_chart(
                evolution_points=comparison.evolution.points
            )
            evolution_chart_html = render_chart_container(
                title="Sales trend comparison",
                image_base64=evolution_base64
            )
        except Exception as e:
            evolution_chart_html = f'<p style="color: red;">Could not build the trend chart: {escape(str(e))}</p>'
    # ============================================================
    # Gráfico de barras comparativo (A vs B)
    # ============================================================

    compare_bar_html = ""

    try:
        labels = ["Sales", "Transactions", "Average sale"]

        values_a = [
            period_a.metrics.total_sales,
            period_a.metrics.transactions,
            period_a.metrics.avg_ticket,
        ]

        values_b = [
            period_b.metrics.total_sales,
            period_b.metrics.transactions,
            period_b.metrics.avg_ticket,
        ]

        compare_bar_base64 = generate_compare_bar_chart(
            labels=labels,
            values_a=values_a,
            values_b=values_b,
            title="A vs. B comparison",
        )

        compare_bar_html = f"""
        <div class="chart-container">
            <h3>A vs. B comparison</h3>
            <img src="data:image/png;base64,{compare_bar_base64}" style="width: 100%;">
        </div>
        """
    except Exception as e:
        compare_bar_html = f'<p style="color: red;">Could not build the comparison chart: {escape(str(e))}</p>'

    #=============================================================
    # Métricas de comparación
    # ============================================================
    
    metrics = comparison.metrics
    abs_changes = metrics.absolute_changes
    pct_changes = metrics.percentage_changes
    
    total_sales_change = abs_changes.get('total_sales', 0)
    transactions_change = abs_changes.get('transactions', 0)
    avg_ticket_change = abs_changes.get('avg_ticket', 0)
    unique_clients_change = abs_changes.get('unique_clients', 0)

    comparison_metrics_html = f'''
    <h2>Comparative analysis</h2>

    {evolution_chart_html}
    {compare_bar_html}
    <div class="comparison-block">
        <h3>Absolute changes (period B - period A)</h3>
        <div class="metrics">
            <div class="metric-card">
                <label>Change in sales (€)</label>
                <div class="value" style="color: {'green' if total_sales_change > 0 else 'red'};">
                    {format_eur_signed(total_sales_change)}
                </div>
            </div>
            <div class="metric-card">
                <label>Change in transactions</label>
                <div class="value" style="color: {'green' if transactions_change > 0 else 'red'};">
                    {transactions_change:+,.0f}
                </div>
            </div>
            <div class="metric-card">
                <label>Change in average sale (€)</label>
                <div class="value" style="color: {'green' if avg_ticket_change > 0 else 'red'};">
                    {format_eur_signed(avg_ticket_change)}
                </div>
            </div>
            <div class="metric-card">
                <label>Change in unique clients</label>
                <div class="value" style="color: {'green' if unique_clients_change > 0 else 'red'};">
                    {unique_clients_change:+,.0f}
                </div>
            </div>
        </div>
    </div>

    <div class="comparison-block">
        <h3>Percentage changes (%)</h3>
        <div class="metrics">
            <div class="metric-card">
                <label>Change in sales</label>
                <div class="value" style="color: {'green' if pct_changes.get('total_sales', 0) > 0 else 'red'};">
                    {pct_changes.get('total_sales', 0):+.1f}%
                </div>
            </div>
            <div class="metric-card">
                <label>Change in transactions</label>
                <div class="value" style="color: {'green' if pct_changes.get('transactions', 0) > 0 else 'red'};">
                    {pct_changes.get('transactions', 0):+.1f}%
                </div>
            </div>
            <div class="metric-card">
                <label>Change in average sale</label>
                <div class="value" style="color: {'green' if pct_changes.get('avg_ticket', 0) > 0 else 'red'};">
                    {pct_changes.get('avg_ticket', 0):+.1f}%
                </div>
            </div>
            <div class="metric-card">
                <label>Change in unique clients</label>
                <div class="value" style="color: {'green' if pct_changes.get('unique_clients', 0) > 0 else 'red'};">
                    {pct_changes.get('unique_clients', 0):+.1f}%
                </div>
            </div>
        </div>
    </div>
    '''
    
    return comparison_metrics_html
