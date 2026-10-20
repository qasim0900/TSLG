"""
Helpers para secciones HTML del informe de ventas.
"""
from html import escape

from .charts_generator import generate_pie_chart, generate_horizontal_bar_chart
from utils.formatting import format_eur_no_symbol


def render_chart_container(
    title: str,
    image_base64: str,
    *,
    subtitle: str | None = None
) -> str:
    """
    Renderiza un contenedor HTML estándar para gráficos.
    
    Formaliza la decisión arquitectónica:
    - El título vive en HTML (semántica, única fuente de verdad)
    - El gráfico es solo imagen base64 (visual puro)
    - Estructura consistente en todo el reporte
    
    Args:
        title: Título del gráfico (obligatorio, se renderiza en <h3>)
        image_base64: String base64 de la imagen PNG
        subtitle: Subtítulo o contexto adicional (opcional)
    
    Returns:
        HTML string listo para insertar en el reporte
    """
    safe_title = escape(str(title))
    subtitle_html = (
        f'<p style="color: #666; font-size: 12px; margin: 4px 0 12px 0;">'
        f'{escape(str(subtitle))}</p>'
        if subtitle
        else ""
    )
    
    return f'''
    <div class="chart-container">
        <h3>{safe_title}</h3>
        {subtitle_html}
        <img src="data:image/png;base64,{image_base64}" alt="{safe_title}" style="width: 100%;">
    </div>
    '''


def render_period_filters(filters):
    start_date = filters.get('start_date')
    end_date = filters.get('end_date')
    first_date = filters.get('first_date')
    last_date = filters.get('last_date')
    period_str = "All records"
    if not start_date and not end_date and first_date and last_date:
        period_str = f"From {first_date} to {last_date}"
    elif start_date and end_date:
        period_str = f"From {start_date} to {end_date}"
    elif start_date:
        period_str = f"From {start_date}"
    elif end_date:
        period_str = f"Until {end_date}"
    filters_html_items = ""
    if filters.get('client_name'):
        filters_html_items += f'''<div class="filter-item">
                <span class="filter-label">Client:</span>
                <span class="filter-value">{escape(str(filters['client_name']))}</span>
            </div>'''
    if filters.get('product_type'):
        filters_html_items += f'''<div class="filter-item">
                <span class="filter-label">Product:</span>
                <span class="filter-value">{escape(str(filters['product_type']))}</span>
            </div>'''
    filters_section = f'<div class="filters-section">{filters_html_items}</div>' if filters_html_items else ""
    return f'''<div class="period-filters">
        <div class="period-section">
            <span class="period-icon">📋</span>
            <span class="period-text">{escape(period_str)}</span>
        </div>
        {filters_section}
    </div>'''

def render_metrics(total_ventas, total_cantidad, promedio, num_productos, unique_clients=0):
    return f'''
    <div class="metrics">
        <div class="metric-card">
            <label>Total sales (€)</label>
            <div class="value">{format_eur_no_symbol(total_ventas)}</div>
        </div>
        <div class="metric-card">
            <label>Total transactions</label>
            <div class="value">{total_cantidad:,.0f}</div>
        </div>
        <div class="metric-card">
            <label>Average sale (€)</label>
            <div class="value">{format_eur_no_symbol(promedio)}</div>
        </div>
        <div class="metric-card">
            <label>Products</label>
            <div class="value">{num_productos}</div>
        </div>
        <div class="metric-card">
            <label>Unique clients</label>
            <div class="value">{unique_clients}</div>
        </div>
    </div>
    '''

def render_charts_section(rows, clients_stats, percentages=None):
    pie_chart_html = ""
    top_clients_html = ""
    if rows:
        try:
            labels = [row[0] for row in rows]
            values = [float(row[1]) for row in rows]
            pie_base64 = generate_pie_chart(labels, values, percentages=percentages)
            pie_chart_html = (
                f'<img src="data:image/png;base64,{pie_base64}" '
                'alt="Sales distribution by product" style="width: 100%;">'
            )
        except Exception as e:
            pie_chart_html = f'<p style="color: red;">Could not build the product chart: {escape(str(e))}</p>'
    if clients_stats is not None and isinstance(clients_stats, list) and len(clients_stats) > 0:
        try:
            client_names = [c.get('name', 'Unnamed') for c in clients_stats]
            client_amounts = [float(c.get('total_amount', 0)) for c in clients_stats]
            bars_base64 = generate_horizontal_bar_chart(
                client_names,
                client_amounts,
                title=None,
                xlabel="Amount spent (€)"
            )
            top_clients_html = (
                f'<img src="data:image/png;base64,{bars_base64}" '
                'alt="Top five clients by sales amount" style="width: 100%;">'
            )
        except Exception as e:
            top_clients_html = f'<p style="color: red;">Could not build the client chart: {escape(str(e))}</p>'
    if not pie_chart_html:
        return ""
    return f'''
    <div class="charts-row">
        <div class="chart-container">
            <h3>Sales distribution by product</h3>
            {pie_chart_html}
        </div>
        {f'''<div class="chart-container">
            <h3>Top 5 clients (by amount)</h3>
            {top_clients_html}
        </div>''' if top_clients_html else ''}
    </div>
    '''

def render_table_rows(rows):
    html = ""
    for row in rows:
        try:
            producto = row[0]
            total = float(row[1])
            cantidad = float(row[2])
            promedio_prod = float(row[3])
            minimo = float(row[4])
            maximo = float(row[5])
            html += f'''<tr>
                <td><strong>{escape(str(producto))}</strong></td>
                <td>{cantidad:,.0f}</td>
                <td>{total:,.2f}</td>
                <td>{promedio_prod:,.2f}</td>
                <td>{minimo:,.2f}</td>
                <td>{maximo:,.2f}</td>
            </tr>
'''
        except (IndexError, ValueError):
            pass
    return html
