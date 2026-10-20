"""
Generación de informe HTML para un cliente individual.

Consume datos ya cargados desde ClientesView (client_info + stats).
NO realiza queries adicionales.
"""
import html
import os
from datetime import datetime
from .html_template import get_html_base
from utils.formatting import format_datetime_us, format_eur_no_symbol


def generate_client_html_report(client_info: dict, stats: dict, filename: str | None = None):
    """
    Genera un informe HTML para un cliente individual.

    Args:
        client_info: dict con keys: client_id, name, cif, address, contact_person, email
        stats: dict de ClientsController.get_client_sales_stats() con keys:
               total_sales (count), total_amount, avg_amount, sales (list of dicts)
        filename: Ruta del archivo (si es None, genera uno automático)

    Returns:
        tuple (success: bool, message: str, filepath: str)
    """
    try:
        name = html.escape(client_info.get('name', 'Client'))

        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = "".join(c for c in client_info.get('name', 'Client') if c.isalnum() or c in (' ', '-', '_')).strip()
            filename = f"Client_Profile_{safe_name}_{timestamp}.html"

        if os.path.dirname(filename):
            os.makedirs(os.path.dirname(filename), exist_ok=True)

        # ── Client info section ──────────────────────────────────
        cif = html.escape(client_info.get('cif') or '—')
        email = html.escape(client_info.get('email') or '—')
        address = html.escape(client_info.get('address') or '—')
        contact_person = html.escape(client_info.get('contact_person') or '—')

        info_html = f'''
        <div class="client-info">
            <div class="info-item">
                <span class="info-label">Name</span>
                <span class="info-value">{name}</span>
            </div>
            <div class="info-item">
                <span class="info-label">Tax ID</span>
                <span class="info-value sensitive" tabindex="0" aria-label="Sensitive tax ID; focus to reveal">{cif}</span>
            </div>
            <div class="info-item">
                <span class="info-label">Email</span>
                <span class="info-value sensitive" tabindex="0" aria-label="Sensitive email; focus to reveal">{email}</span>
            </div>
            <div class="info-item">
                <span class="info-label">Contact person</span>
                <span class="info-value sensitive" tabindex="0" aria-label="Sensitive contact person; focus to reveal">{contact_person}</span>
            </div>
            <div class="info-item">
                <span class="info-label">Address</span>
                <span class="info-value">{address}</span>
            </div>
        </div>
        '''

        # ── Metrics section ──────────────────────────────────────
        total_sales_count = stats.get('total_sales', 0)
        total_amount = stats.get('total_amount', 0)
        avg_amount = stats.get('avg_amount', 0)

        metrics_html = f'''
        <div class="metrics">
            <div class="metric-card accent-green">
                <label>Total spent (€)</label>
                <div class="value">{format_eur_no_symbol(total_amount)}</div>
            </div>
            <div class="metric-card accent-purple">
                <label>Transactions</label>
                <div class="value">{total_sales_count}</div>
            </div>
            <div class="metric-card accent-orange">
                <label>Average sale (€)</label>
                <div class="value">{format_eur_no_symbol(avg_amount)}</div>
            </div>
        </div>
        '''

        # ── Sales history table ──────────────────────────────────
        sales_list = stats.get('sales', [])
        table_html = ""
        if sales_list:
            rows_html = ""
            for sale in sales_list:
                sale_date = html.escape(str(sale.get('date', '—')))
                product = html.escape(str(sale.get('product_type', '—')))
                price = float(sale.get('price', 0))
                rows_html += f'''<tr>
                    <td>{sale_date}</td>
                    <td>{product}</td>
                    <td>{format_eur_no_symbol(price)}</td>
                </tr>
'''

            table_html = f'''
            <h2>Purchase history</h2>
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Product</th>
                        <th>Amount (€)</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
            '''

        # ── Assemble content ─────────────────────────────────────
        content_block = f'''
        <div class="header">
            <div class="brand">Techset LeadGen</div>
            <h1>Client Profile</h1>
            <p>Generated on {format_datetime_us(datetime.now())}</p>
        </div>
        <div class="content">
            <h2>Client information</h2>
            {info_html}
            <h2>Sales summary</h2>
            {metrics_html}
            {table_html}
        </div>
        <div class="footer">
            <p><strong>Techset LeadGen</strong></p>
            <p>Report generated automatically by the client management system.</p>
            <p>&copy; {datetime.now().year} Techset LeadGen.</p>
        </div>
        '''

        html_content = get_html_base(
            content_block,
            title=f"Techset LeadGen - Client Profile - {name}",
        )

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return (True, f"Report generated: {os.path.basename(filename)}", filename)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return (False, f"Could not generate the client report: {str(e)}", None)
