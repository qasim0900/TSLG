def get_html_base(content: str, title: str = "Techset LeadGen Report") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        /* ── CSS Variables ─────────────────────────────────────── */
        :root {{
            --clr-primary:       #39B54A;
            --clr-primary-dark:  #0A1414;
            --clr-primary-light: #32CD32;
            --clr-accent:        #FFCB4A;
            --clr-action:        #176B2C;
            --clr-text:          #0A1414;
            --clr-brand-muted:   #757693;
            --clr-muted:         #62637A;
            --clr-surface:       #FBFAF8;
            --clr-border:        rgba(117,118,147,.24);
            --radius:            14px;
            --radius-sm:          8px;
            --shadow-card:       0 1px 3px rgba(0,0,0,.05), 0 4px 16px rgba(0,0,0,.06);
            --shadow-container:  0 1px 3px rgba(0,0,0,.04), 0 8px 28px rgba(0,0,0,.08), 0 36px 80px rgba(0,0,0,.05);
            --transition:        150ms ease;
        }}

        /* ── Reset & base ──────────────────────────────────────── */
        *, *::before, *::after {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        html {{
            scroll-behavior: smooth;
        }}
        body {{
            font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
            background-color: var(--clr-surface);
            background-image: radial-gradient(circle, rgba(10,20,20,.12) 1px, transparent 1px);
            background-size: 28px 28px;
            color: var(--clr-text);
            padding: 32px 16px;
            line-height: 1.6;
            -webkit-font-smoothing: antialiased;
            font-variant-numeric: tabular-nums;
        }}

        /* ── Container ─────────────────────────────────────────── */
        .container {{
            max-width: 1200px;
            width: 100%;
            margin: 0 auto;
            background: #ffffff;
            border-radius: 20px;
            border: 1px solid var(--clr-border);
            box-shadow: var(--shadow-container);
            overflow: hidden;
        }}

        /* ── Header ────────────────────────────────────────────── */
        .header {{
            background: linear-gradient(135deg, var(--clr-primary-dark) 0%, #153724 100%);
            color: #ffffff;
            padding: 52px 48px 44px;
            text-align: center;
            position: relative;
            overflow: hidden;
        }}
        /* Subtle radial glow overlays — sin imágenes externas */
        .header::before {{
            content: '';
            position: absolute;
            inset: 0;
            background:
                radial-gradient(ellipse at 15% 60%, rgba(255,255,255,.09) 0%, transparent 55%),
                radial-gradient(ellipse at 85% 25%, rgba(255,255,255,.06) 0%, transparent 45%);
            pointer-events: none;
        }}
        /* Bottom gradient accent strip */
        .header::after {{
            content: '';
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, var(--clr-primary), var(--clr-primary-light), var(--clr-accent));
        }}
        .brand {{
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 3px;
            opacity: 0.72;
            margin-bottom: 18px;
            position: relative;
        }}
        .header h1 {{
            font-size: 28px;
            font-weight: 700;
            letter-spacing: -0.5px;
            margin-bottom: 10px;
            position: relative;
        }}
        .header p {{
            font-size: 13px;
            opacity: 0.72;
            font-weight: 400;
            position: relative;
        }}

        /* ── Content ───────────────────────────────────────────── */
        .content {{
            padding: 44px 48px;
        }}

        /* ── Section titles ────────────────────────────────────── */
        .content h2 {{
            font-size: 19px;
            font-weight: 700;
            color: var(--clr-text);
            margin: 44px 0 20px;
            padding: 0 0 12px 14px;
            border-left: 4px solid var(--clr-primary);
            border-bottom: 1px solid var(--clr-border);
        }}
        .content h2:first-child {{
            margin-top: 0;
        }}
        .content h3 {{
            font-size: 15px;
            font-weight: 600;
            color: var(--clr-text);
            margin: 28px 0 14px;
        }}

        /* ── Period filters ────────────────────────────────────── */
        .period-filters {{
            background: var(--clr-surface);
            border: 1px solid var(--clr-border);
            border-left: 4px solid var(--clr-primary);
            padding: 20px 24px;
            border-radius: var(--radius-sm);
            margin-bottom: 28px;
            box-shadow: 0 1px 4px rgba(0,0,0,.04);
        }}
        .period-section {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .period-icon {{
            font-size: 18px;
        }}
        .period-text {{
            font-size: 15px;
            font-weight: 600;
            color: var(--clr-action);
        }}
        .filters-section {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 14px;
        }}
        .filter-item {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 14px;
            background: #ffffff;
            border-radius: 20px;
            border: 1px solid var(--clr-border);
            font-size: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,.04);
        }}
        .filter-label {{
            color: var(--clr-muted);
            font-weight: 500;
        }}
        .filter-value {{
            color: var(--clr-action);
            font-weight: 600;
        }}

        /* ── Metric cards ──────────────────────────────────────── */
        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            margin-bottom: 40px;
        }}
        .metric-card {{
            background: var(--clr-surface);
            border: 1px solid var(--clr-border);
            border-radius: var(--radius);
            padding: 24px 20px 20px;
            position: relative;
            overflow: hidden;
            transition: transform var(--transition), box-shadow var(--transition);
        }}
        .metric-card:hover {{
            transform: translateY(-3px);
            box-shadow: 0 8px 28px rgba(0,0,0,.11);
        }}
        /* Accent bar en la parte superior (más moderno que lateral) */
        .metric-card::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: var(--clr-primary);
            border-radius: var(--radius) var(--radius) 0 0;
        }}
        .metric-card label {{
            display: block;
            font-size: 10px;
            font-weight: 700;
            color: var(--clr-muted);
            text-transform: uppercase;
            letter-spacing: 0.8px;
            margin-bottom: 10px;
        }}
        .metric-card .value {{
            font-size: 28px;
            font-weight: 700;
            color: var(--clr-action);
            line-height: 1.15;
            letter-spacing: -0.5px;
            font-variant-numeric: tabular-nums;
        }}

        /* Variantes de color */
        .metric-card.accent-green::before  {{ background: var(--clr-primary); }}
        .metric-card.accent-green .value   {{ color: var(--clr-action); }}
        .metric-card.accent-orange::before {{ background: #e65100; }}
        .metric-card.accent-orange .value  {{ color: #e65100; }}
        .metric-card.accent-purple::before {{ background: #6a1b9a; }}
        .metric-card.accent-purple .value  {{ color: #6a1b9a; }}
        .metric-card.accent-teal::before   {{ background: #00695c; }}
        .metric-card.accent-teal .value    {{ color: #00695c; }}
        .metric-card.accent-red::before    {{ background: #c62828; }}
        .metric-card.accent-red .value     {{ color: #c62828; }}

        /* ── Charts ────────────────────────────────────────────── */
        .charts-row {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 20px;
            margin: 32px 0;
        }}
        .chart-container {{
            background: var(--clr-surface);
            padding: 24px;
            border-radius: var(--radius);
            border: 1px solid var(--clr-border);
            text-align: center;
            box-shadow: var(--shadow-card);
        }}
        .chart-container h3 {{
            margin: 0 0 18px;
            color: var(--clr-text);
            font-size: 15px;
            font-weight: 600;
        }}
        .chart-container img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
        }}

        /* ── Tables ────────────────────────────────────────────── */
        /* border-collapse:separate + border-spacing:0 permite border-radius real en la tabla */
        table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            margin-top: 16px;
            margin-bottom: 8px;
            font-size: 14px;
            border-radius: var(--radius);
            overflow: hidden;
            border: 1px solid var(--clr-border);
            box-shadow: var(--shadow-card);
        }}
        thead th {{
            background: var(--clr-action);
            color: #ffffff;
            padding: 13px 16px;
            text-align: left;
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            white-space: nowrap;
        }}
        td {{
            padding: 12px 16px;
            border-bottom: 1px solid var(--clr-border);
            color: var(--clr-text);
            vertical-align: middle;
        }}
        tbody tr:last-child td {{
            border-bottom: none;
        }}
        tr:hover td {{
            background: rgba(57,181,74,.09);
        }}
        tr:nth-child(even) td {{
            background: var(--clr-surface);
        }}
        tr:nth-child(even):hover td {{
            background: rgba(57,181,74,.13);
        }}

        /* ── Comparison section ────────────────────────────────── */
        .comparison-block {{
            background: var(--clr-surface);
            padding: 24px;
            border-radius: var(--radius);
            border: 1px solid var(--clr-border);
            margin-bottom: 24px;
            box-shadow: var(--shadow-card);
        }}
        .comparison-block h3 {{
            color: var(--clr-muted);
            font-size: 13px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin: 0 0 16px;
        }}

        /* ── Client info card ──────────────────────────────────── */
        .client-info {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            background: var(--clr-surface);
            border: 1px solid var(--clr-border);
            border-radius: var(--radius);
            padding: 28px;
            margin-bottom: 32px;
            box-shadow: var(--shadow-card);
        }}
        .client-info .info-item {{
            display: flex;
            flex-direction: column;
            gap: 5px;
        }}
        .client-info .info-label {{
            font-size: 10px;
            font-weight: 700;
            color: var(--clr-muted);
            text-transform: uppercase;
            letter-spacing: 0.7px;
        }}
        .client-info .info-value {{
            font-size: 15px;
            font-weight: 500;
            color: var(--clr-text);
            line-height: 1.4;
        }}

        /* ── Funnel section (leads) ────────────────────────────── */
        .funnel-stage {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 16px 20px;
            border-radius: var(--radius-sm);
            margin-bottom: 8px;
            position: relative;
            overflow: hidden;
            border: 1px solid rgba(0,0,0,.04);
        }}
        .funnel-stage .stage-bar {{
            position: absolute;
            top: 0;
            left: 0;
            height: 100%;
            opacity: 0.10;
            border-radius: var(--radius-sm);
        }}
        .funnel-stage .stage-label {{
            font-weight: 600;
            font-size: 14px;
            flex: 1;
            z-index: 1;
        }}
        .funnel-stage .stage-value {{
            font-weight: 700;
            font-size: 20px;
            z-index: 1;
            font-variant-numeric: tabular-nums;
        }}
        .funnel-stage .stage-pct {{
            font-size: 13px;
            color: var(--clr-muted);
            font-weight: 500;
            z-index: 1;
            min-width: 54px;
            text-align: right;
        }}

        /* ── Status badges ─────────────────────────────────────── */
        .badge {{
            display: inline-block;
            padding: 3px 11px;
            border-radius: 20px;
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.4px;
            box-shadow: 0 1px 3px rgba(0,0,0,.08);
        }}
        .badge-new       {{ background: rgba(57,181,74,.16); color: var(--clr-action); }}
        .badge-contacted {{ background: #ede9fe; color: #6b21a8; }}
        .badge-qualified {{ background: #dcfce7; color: #166534; }}
        .badge-nurture {{ background: #fef9c3; color: #854d0e; }}
        .badge-meeting   {{ background: #ffedd5; color: #c2410c; }}
        .badge-converted {{ background: #dcfce7; color: #166534; }}
        .badge-lost      {{ background: #fee2e2; color: #991b1b; }}

        /* ── Footer ────────────────────────────────────────────── */
        .footer {{
            background: var(--clr-surface);
            padding: 28px 48px;
            text-align: center;
            font-size: 12px;
            color: var(--clr-muted);
            position: relative;
        }}
        /* Separador con gradiente que se desvanece en los extremos */
        .footer::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 48px;
            right: 48px;
            height: 1px;
            background: linear-gradient(90deg, transparent, var(--clr-border) 20%, var(--clr-border) 80%, transparent);
        }}
        .footer p {{
            margin: 5px 0;
        }}
        .footer strong {{
            color: var(--clr-text);
        }}

        /* ── Datos sensibles (blur hover-reveal) ───────────────── */
        .sensitive {{
            filter: blur(5px);
            cursor: pointer;
            transition: filter 0.25s ease;
            user-select: none;
            border-radius: 3px;
            display: inline-block;
        }}
        .sensitive:hover,
        .sensitive:focus {{
            filter: blur(0);
            user-select: auto;
            outline: 2px solid var(--clr-action);
            outline-offset: 3px;
        }}

        /* ── Print styles ──────────────────────────────────────── */
        @media print {{
            body {{
                background: white;
                background-image: none;
                padding: 0;
            }}
            .container {{
                box-shadow: none;
                border-radius: 0;
                border: none;
            }}
            .metric-card {{ transition: none; }}
            .metric-card:hover {{ transform: none; box-shadow: none; }}
            .chart-container {{ break-inside: avoid; }}
            table {{ break-inside: avoid; box-shadow: none; }}
            /* Al imprimir, los datos sensibles se muestran completos */
            .sensitive {{ filter: none; user-select: auto; }}
        }}

        /* ── Responsive ────────────────────────────────────────── */
        @media (max-width: 768px) {{
            body {{ padding: 8px; }}
            .content {{ padding: 24px 20px; }}
            .header {{ padding: 36px 24px; }}
            table {{
                display: block;
                overflow-x: auto;
                white-space: nowrap;
                -webkit-overflow-scrolling: touch;
            }}
            .metrics {{
                grid-template-columns: 1fr 1fr;
                gap: 12px;
            }}
            .metric-card {{ padding: 18px 16px 16px; }}
            .metric-card .value {{ font-size: 22px; }}
            .client-info {{ grid-template-columns: 1fr; }}
            .footer {{ padding: 24px 20px; }}
            .footer::before {{ left: 20px; right: 20px; }}
        }}
        @media (max-width: 480px) {{
            .metrics {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="container">{content}</div>
</body>
</html>
"""

