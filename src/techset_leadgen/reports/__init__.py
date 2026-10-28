"""
Módulo reports: generación de reportes.
"""
from techset_leadgen.reports.report_html import generate_html_report_from_snapshot
from techset_leadgen.reports.report_client_html import generate_client_html_report
from techset_leadgen.reports.report_leads_html import generate_leads_html_report

__all__ = [
    'generate_html_report_from_snapshot',
    'generate_client_html_report',
    'generate_leads_html_report',
]

