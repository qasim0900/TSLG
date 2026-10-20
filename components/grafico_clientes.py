"""
Componentes para análisis de clientes.
- Gráfico de clientes top (más compras)
- Gráfico de monto gastado por cliente
Estilo visual consistente con GraficoCircularHover (pie chart).

Implementación: Patrón B (mutación + update)
- update_theme(): SOLO muta propiedades visuales
- update_from_data(): Reconstruye cuando cambian datos
"""
import flet as ft
from theme import get_text_color, get_tops_chart_palette
from components.bar_chart_helpers import build_ranked_bar
from utils.formatting import format_eur


class GraficoClientesTop(ft.Container):
    """
    Gráfico de barras: Top clientes por número de compras
    
    Ciclo de vida:
    1. __init__: Ordenar, construir UI, guardar referencias
    2. update_from_data(): Cambiar datos, reconstruir
    3. update_theme(): SOLO mutar colores
    """
    
    def __init__(self, clients_data, theme_mode=ft.ThemeMode.LIGHT, limit=10):
        """
        clients_data: lista de dicts con {name, total_sales, total_amount, avg_amount}
        theme_mode: tema actual
        limit: cantidad de clientes a mostrar (top N)
        """
        self._clients_data = clients_data
        self._theme_mode = theme_mode
        self._limit = limit
        
        # Datos ordenados (guardar para evitar reordenar en update_theme)
        self._sorted_clients = []
        self._max_sales = 1
        
        # Referencias a UI para mutar en update_theme()
        self._bar_texts_unit = []
        self._bar_containers = []
        self._bar_texts_name = []
        self._bar_texts_value = []
        self._palette = []
        
        # Mismo estilo que GraficoCircularHover (pie chart)
        super().__init__(
            content=self._build_chart(),
            padding=12,
            bgcolor=ft.Colors.SURFACE,
            border_radius=8,
            expand=True,
        )
    
    def update_theme(self, theme_mode):
        """
        Actualiza el gráfico según el nuevo tema (Patrón B).
        
        🚨 SOLO muta propiedades visuales:
        - Paleta de colores
        - Text.color
        - Container.bgcolor (barras)
        
        ❌ NO reconstruye, NO reordena
        """
        self._theme_mode = theme_mode
        text_color = get_text_color(self._theme_mode)

        # Recalcular paleta según tema
        self._palette = get_tops_chart_palette(self._theme_mode, count=len(self._sorted_clients))
        
        # Mutar colores en barras
        for idx, container in enumerate(self._bar_containers):
            if idx < len(self._palette):
                container.bgcolor = self._palette[idx % len(self._palette)]
        
        # Mutar colores en textos
        for text in self._bar_texts_name:
            text.color = text_color
        for text in self._bar_texts_value:
            text.color = text_color
        for text in self._bar_texts_unit:
            text.color = text_color
        
        # NO llamar self.update() - VentasView llama page.update() al final
    
    def update_from_data(self, clients_data):
        """
        Actualiza el gráfico con nuevos datos.
        Reconstrucción completa y segura.
        """
        self._clients_data = clients_data
    
        # Limpiar referencias internas (seguridad total)
        self._sorted_clients = []
        self._bar_containers = []
        self._bar_texts_name = []
        self._bar_texts_value = []
        self._bar_texts_unit = []
    
        # Reconstruir contenido
        new_chart = self._build_chart()

        # Mutar .content — VentasView orquesta page.update() al final
        self.content = new_chart

    
    def _build_chart(self):
        """Construye el gráfico de clientes top"""
        text_color = get_text_color(self._theme_mode)
        
        if not self._clients_data:
            return ft.Text(
                "⚠ No client data.",
                size=16,
                color=text_color
            )
        
        # Ordenar por número de compras (total_sales) UNA SOLA VEZ
        self._sorted_clients = sorted(
            self._clients_data, 
            key=lambda x: x.get('total_sales', 0), 
            reverse=True
        )[:self._limit]
        
        if not self._sorted_clients:
            return ft.Text("⚠ No data.", size=16, color=text_color)
        
        # Obtener max valor para escala UNA SOLA VEZ
        self._max_sales = max(c.get('total_sales', 0) for c in self._sorted_clients)
        if self._max_sales == 0:
            self._max_sales = 1
        
        self._palette = get_tops_chart_palette(self._theme_mode, count=len(self._sorted_clients))
        
        # Limpiar referencias previas
        self._bar_containers = []
        self._bar_texts_name = []
        self._bar_texts_value = []
        self._bar_texts_unit = []

        # Construir barras (guardar referencias para update_theme)
        bars_ui = []
        for idx, client in enumerate(self._sorted_clients):
            name = client.get('name', 'Unnamed')
            sales = client.get('total_sales', 0)
            pct = (sales / self._max_sales) * 100 if self._max_sales else 0
            percentage = client.get('percentage', 0.0)
            pct_label = f" ({percentage:.1f}% of total)" if percentage else ""
            column, bar, value_text, unit_text, name_text = build_ranked_bar(
                name=name,
                value=str(sales),
                pct=pct,
                idx=idx,
                palette=self._palette,
                unit_label="compras",
                tooltip=f"{'🏆 ' if idx == 0 else ''}{name}: {sales} compras{pct_label}",
            )

            self._bar_containers.append(bar)
            self._bar_texts_value.append(value_text)
            self._bar_texts_name.append(name_text)
            self._bar_texts_unit.append(unit_text)
            bars_ui.append(column)

        
        return ft.Row(
            bars_ui,
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.END,
            expand=True,
            wrap=True,
        )


class GraficoClientesMonto(ft.Container):
    """
    Gráfico de barras: Clientes por monto total gastado
    
    Ciclo de vida:
    1. __init__: Ordenar, construir UI, guardar referencias
    2. update_from_data(): Cambiar datos, reconstruir
    3. update_theme(): SOLO mutar colores
    """
    
    def __init__(self, clients_data, theme_mode=ft.ThemeMode.LIGHT, limit=10):
        """
        clients_data: lista de dicts con {name, total_sales, total_amount, avg_amount}
        theme_mode: tema actual
        limit: cantidad de clientes a mostrar
        """
        self._clients_data = clients_data
        self._theme_mode = theme_mode
        self._limit = limit
        
        # Datos ordenados (guardar para evitar reordenar en update_theme)
        self._sorted_clients = []
        self._max_amount = 1
        
        # Referencias a UI para mutar en update_theme()
        self._bar_containers = []
        self._bar_texts_name = []
        self._bar_texts_value = []
        self._palette = []
        self._bar_texts_unit = []

        # Mismo estilo que GraficoCircularHover (pie chart)
        super().__init__(
            content=self._build_chart(),
            padding=12,
            bgcolor=ft.Colors.SURFACE,
            border_radius=8,
            expand=True,
        )

    def update_theme(self, theme_mode):
        """
        Actualiza el gráfico según el nuevo tema (Patrón B).
        
        🚨 SOLO muta propiedades visuales:
        - Paleta de colores
        - Text.color
        - Container.bgcolor (barras)
        
        ❌ NO reconstruye, NO reordena
        """
        self._theme_mode = theme_mode
        text_color = get_text_color(self._theme_mode)
        
        # Recalcular paleta según tema
        self._palette = get_tops_chart_palette(self._theme_mode, count=len(self._sorted_clients))
        
        # Mutar colores en barras
        for idx, container in enumerate(self._bar_containers):
            if idx < len(self._palette):
                container.bgcolor = self._palette[idx % len(self._palette)]
        
        # Mutar colores en textos
        for text in self._bar_texts_name:
            text.color = text_color
        for text in self._bar_texts_value:
            text.color = text_color
        for text in self._bar_texts_unit:
            text.color = text_color
        
        # NO llamar self.update() - VentasView llama page.update() al final
    
    def update_from_data(self, clients_data):
        """
        Actualiza el gráfico con nuevos datos.
        
        Aquí SÍ recalculamos y reconstruimos.
        """
        self._clients_data = clients_data
        self.content = self._build_chart()
    
    def _build_chart(self):
        """Construye el gráfico de monto por cliente"""
        text_color = get_text_color(self._theme_mode)
        
        if not self._clients_data:
            return ft.Text(
                "⚠ No client data.",
                size=16,
                color=text_color
            )
        
        # Ordenar por monto gastado (total_amount) UNA SOLA VEZ
        self._sorted_clients = sorted(
            self._clients_data,
            key=lambda x: float(x.get('total_amount', 0)),
            reverse=True
        )[:self._limit]
        
        if not self._sorted_clients:
            return ft.Text("⚠ No data.", size=16, color=text_color)
        
        # Obtener max valor para escala UNA SOLA VEZ
        self._max_amount = max(float(c.get('total_amount', 0)) for c in self._sorted_clients)
        if self._max_amount == 0:
            self._max_amount = 1
        
        self._palette = get_tops_chart_palette(self._theme_mode, count=len(self._sorted_clients))
        
        # Limpiar referencias previas
        self._bar_containers = []
        self._bar_texts_name = []
        self._bar_texts_value = []
        self._bar_texts_unit = []

        # Construir barras (guardar referencias para update_theme)
        bars_ui = []
        for idx, client in enumerate(self._sorted_clients):
            name = client.get('name', 'Unnamed')
            amount = float(client.get('total_amount', 0))
            pct = (amount / self._max_amount) * 100 if self._max_amount else 0
            
            percentage = client.get('percentage', 0.0)
            pct_label = f" ({percentage:.1f}% of total)" if percentage else ""
            column, bar, value_text, unit_text, name_text = build_ranked_bar(
                name=name,
                value=format_eur(amount, decimals=0),
                pct=pct,
                idx=idx,
                palette=self._palette,
                unit_label="€ total",
                tooltip=f"{'🏆 ' if idx == 0 else ''}{name}: {format_eur(amount)}{pct_label}",
            )
            self._bar_containers.append(bar)
            self._bar_texts_value.append(value_text)
            self._bar_texts_name.append(name_text)
            self._bar_texts_unit.append(unit_text)

            bars_ui.append(column)


        
                
        return ft.Row(
                bars_ui,
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.END,
                expand=True,
                wrap=True,
        )
