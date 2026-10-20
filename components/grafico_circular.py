"""
PIECHARTV2 - Gráfico circular interactivo (Flet 0.80.5)
═══════════════════════════════════════════════════════════

Caracteristicas:
  ✅ Patrones OFICIALES de Flet 0.80.5
  ✅ Hover con expansión visual (radius + border)
  ✅ Información centralizada en el centro
  ✅ Badges de ranking (Top 3)
  ✅ Animaciones suaves
  ✅ R7 compliance (THEME_AGENTS.md)
  ✅ Datos sin cambios (PieChartSnapshot igual)

No usa:
  ❌ Tooltip personalizado (no funciona)
  ❌ Container.visible sin update
  ❌ Asignación a Text anidado

Arquitectura:
  - PieChartTheme: Configuración visual
  - PieChartInteractive: Componente principal
"""

import flet as ft
import flet_charts as ftc
from dataclasses import dataclass, field
from typing import Optional, Callable, List

from domain.analysis_snapshot import PieChartSnapshot
from theme import get_text_color, get_chart_palette, get_card_color
from theme.theme_utils import get_chart_label_color
from utils.formatting import format_eur


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE ESTILOS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PieChartTheme:
    """Tema visual del pie chart interactivo"""
    
    # Radios (basados en ejemplo oficial Flet 0.80.5)
    normal_radius: float = 100.0  # Oficial: 100
    hover_radius: float = 110.0   # Oficial: 110 (expande solo +10px)
    
    # BorderSide
    normal_border: ft.BorderSide = field(
        default_factory=lambda: ft.BorderSide(0, ft.Colors.with_opacity(0, ft.Colors.ON_SURFACE))
    )
    hover_border: ft.BorderSide = field(
        default_factory=lambda: ft.BorderSide(4, ft.Colors.SECONDARY)
    )
    
    # Animación
    animation: ft.Animation = field(
        default_factory=lambda: ft.Animation(
            duration=300,
            curve=ft.AnimationCurve.EASE_OUT
        )
    )
    
    # Tamaños de fuente (basados en ejemplo oficial)
    title_size_normal: float = 12.0  # Oficial: 12
    title_size_hover: float = 16.0   # Oficial: 16
    
    # Badges (basados en ejemplo oficial)
    show_badges: bool = True
    badge_size: float = 40.0  # Oficial: 40
    badge_position: float = 0.98


# ═══════════════════════════════════════════════════════════════════════════
# COMPONENTE PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════

class PieChartInteractive(ft.Container):
    """
    Gráfico circular interactivo con Flet 0.80.5
    
    Entrada:
      snapshot: PieChartSnapshot (mismo formato actual)
      theme_mode: ft.ThemeMode
      theme: Optional[PieChartTheme]
      on_hover_section: Optional callback para eventos de hover
      on_unhover: Optional callback para eventos de salida
    
    Características:
      - Hover con expansión visual (radius + border)
      - Información centralizada en centro
      - Badges ranking (Top 3)
      - Animaciones suaves (300ms)
      - R7 compliant
    
    Métodos públicos:
      - update_from_snapshot(new: PieChartSnapshot)
      - update_theme(new_mode: ft.ThemeMode)
    """
    
    def __init__(
        self,
        snapshot: PieChartSnapshot,
        theme_mode: ft.ThemeMode = ft.ThemeMode.LIGHT,
        theme: Optional[PieChartTheme] = None,
        on_hover_section: Optional[Callable[[int], None]] = None,
        on_unhover: Optional[Callable[[], None]] = None,
    ):
        self._snapshot = snapshot
        # FIX #4: Normalizar theme_mode (validar tipo)
        self._theme_mode = (
            theme_mode if isinstance(theme_mode, ft.ThemeMode) 
            else ft.ThemeMode.LIGHT
        )
        self._theme = theme or PieChartTheme()
        self._on_hover_section = on_hover_section
        self._on_unhover = on_unhover
        
        # Paleta de colores
        self._palette = get_chart_palette(self._theme_mode)
        
        # Referencias a controles
        self._chart: Optional[ftc.PieChart] = None
        self._sections_ui: List[ftc.PieChartSection] = []
        self._badge_texts: List[ft.Text] = []
        self._badge_containers: List[ft.Container] = []
        self._center_info_container: Optional[ft.Container] = None
        self._legend_column: Optional[ft.Column] = None
        self._title_text: Optional[ft.Text] = None
        self._subtitle_text: Optional[ft.Text] = None
        self._legend_title_text: Optional[ft.Text] = None
        self._legend_texts: List[ft.Text] = []
        self._legend_color_boxes: List[ft.Container] = []
        
        # Construir interfaz
        super().__init__(
            content=self._build_ui(),
            padding=12,
            bgcolor=get_card_color(self._theme_mode),
            border_radius=8,
            expand=True,
        )
    
    def _build_ui(self) -> ft.Control:
        """Construir interfaz principal"""
        text_color = get_text_color(self._theme_mode)
        
        # Título
        self._title_text = ft.Text(
            self._snapshot.title,
            size=18,
            weight=ft.FontWeight.BOLD,
            color=text_color,
        )
        
        # Subtítulo con estadísticas
        self._subtitle_text = ft.Text(
            self._get_subtitle_text(),
            size=12,
            color=ft.Colors.with_opacity(0.7, text_color),
        )
        
        # Construir secciones con badges
        self._sections_ui = self._build_sections()
        
        # Centro (información al hovear)
        self._center_info_container = self._build_center_info()
        
        # PieChart (patrón oficial Flet 0.80.5)
        self._chart = ftc.PieChart(
            sections=self._sections_ui,
            sections_space=2,
            center_space_radius=60,  # Espacio para tooltip compacto
            expand=True,
            animation=self._theme.animation,
            on_event=self._on_chart_event,
        )
        
        # Leyenda
        self._legend_column = self._build_legend()
        
        # Layout: 3 columnas — hover izquierda | gráfico centro | leyenda derecha
        return ft.Column(
            [
                self._title_text,
                self._subtitle_text,
                ft.Row(
                    [
                        # Columna izquierda: tarjeta hover (zona vacía aprovechada)
                        ft.Container(
                            content=ft.Column(
                                [self._center_info_container],
                                alignment=ft.MainAxisAlignment.CENTER,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                expand=True,
                            ),
                            width=230,
                            height=500,
                        ),
                        # Columna central: gráfico
                        ft.Container(
                            content=self._chart,
                            height=500,
                            expand=True,
                        ),
                        # Columna derecha: leyenda
                        self._legend_column,
                    ],
                    spacing=20,
                    expand=True,
                ),
            ],
            spacing=12,
            expand=True,
        )
    
    def _build_sections(self) -> List[ftc.PieChartSection]:
        """Construir secciones con badges para Top 3"""
        sections = []
        self._badge_texts = []
        self._badge_containers = []
        
        for idx, segment in enumerate(self._snapshot.segments):
            color = self._palette[segment.color_index % len(self._palette)]
            
            # Badge: mostrar ranking para Top 3
            badge = None
            if self._theme.show_badges and idx < 3:
                # FIX #2: Usar colores semánticos en lugar de hardcoded
                badge_colors = [
                    ft.Colors.PRIMARY,      # Rank #1
                    ft.Colors.SECONDARY,    # Rank #2  
                    ft.Colors.TERTIARY,     # Rank #3
                ]
                badge_text = ft.Text(
                        str(idx + 1),
                        color=ft.Colors.ON_PRIMARY,
                        weight=ft.FontWeight.BOLD,
                        size=16,  # Proporcionado a badge de 40px
                    )
                badge = ft.Container(
                    badge_text,
                    width=self._theme.badge_size,
                    height=self._theme.badge_size,
                    bgcolor=badge_colors[idx],
                    border_radius=self._theme.badge_size / 2,
                    alignment=ft.Alignment(0, 0),  # Centrado
                    shadow=ft.BoxShadow(
                        blur_radius=4,
                        color=ft.Colors.with_opacity(0.3, ft.Colors.ON_SURFACE),
                    ),
                )
                self._badge_texts.append(badge_text)
                self._badge_containers.append(badge)
            
            section = ftc.PieChartSection(
                value=segment.value,
                title=segment.label,
                title_style=ft.TextStyle(
                    size=self._theme.title_size_normal,
                    color=get_chart_label_color(self._theme_mode),
                    weight=ft.FontWeight.BOLD,
                ),
                color=color,
                radius=self._theme.normal_radius,
                border_side=self._theme.normal_border,
                badge=badge,
                badge_position=self._theme.badge_position,
            )
            sections.append(section)
        
        return sections
    
    def _build_center_info(self) -> ft.Container:
        """Construir contenedor para información de hover (debajo de leyenda)"""
        text_color = get_text_color(self._theme_mode)
        card_bg = get_card_color(self._theme_mode)
        
        return ft.Container(
            visible=False,
            bgcolor=card_bg,
            border_radius=12,
            padding=ft.Padding.all(16),
            border=ft.Border.all(2, ft.Colors.PRIMARY),
            width=210,
            shadow=ft.BoxShadow(
                blur_radius=12,
                offset=ft.Offset(0, 4),
                color=ft.Colors.with_opacity(0.18, ft.Colors.ON_SURFACE),
            ),
            content=ft.Column(
                [
                    ft.Text("—", size=15, weight=ft.FontWeight.BOLD, color=text_color),   # Nombre
                    ft.Divider(height=6, color=ft.Colors.with_opacity(0.2, ft.Colors.PRIMARY)),
                    ft.Text("—", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),  # Valor €
                    ft.Text("—", size=13, color=ft.Colors.with_opacity(0.75, text_color)),  # %
                    ft.Text("—", size=12, color=ft.Colors.SECONDARY),                        # Ranking
                ],
                spacing=6,
                tight=True,
            ),
        )
    
    def _build_legend(self) -> ft.Column:
        """Construir leyenda con datos"""
        text_color = get_text_color(self._theme_mode)
        
        legend_items = []
        self._legend_texts = []
        self._legend_color_boxes = []
        for segment in self._snapshot.segments:
            color = self._palette[segment.color_index % len(self._palette)]
            
            color_box = ft.Container(
                width=16,
                height=16,
                bgcolor=color,
                border_radius=4,
            )
            self._legend_color_boxes.append(color_box)

            label_text = ft.Text(
                segment.label,
                size=12,
                color=text_color,
                expand=True,
            )
            value_text = ft.Text(
                format_eur(segment.value),
                size=12,
                weight=ft.FontWeight.W_600,
                color=text_color,
            )
            pct_text = ft.Text(
                f"{segment.percentage:.1f}%",
                size=12,
                weight=ft.FontWeight.W_600,
                color=text_color,
                width=50,
            )
            self._legend_texts.extend([label_text, value_text, pct_text])

            item = ft.Row(
                [
                    color_box,
                    label_text,
                    value_text,
                    pct_text,
                ],
                spacing=10,
            )
            legend_items.append(item)
        
        # Título de leyenda
        self._legend_title_text = ft.Text(
            "Details",
            size=14,
            weight=ft.FontWeight.BOLD,
            color=text_color,
        )
        
        # Leyenda SIN info de hover (se movió a la columna izquierda)
        legend_column = ft.Column(
            [
                self._legend_title_text,
                ft.Column(
                    legend_items,
                    spacing=8,
                    scroll=ft.ScrollMode.AUTO,
                    height=240,
                ),
            ],
            spacing=10,
            width=280,  # ✅ ANCHO FIJO para evitar que comprima el gráfico
        )
        
        return legend_column
    
    def _on_chart_event(self, e: ftc.PieChartEvent):
        """
        Handler de eventos del gráfico
        
        ✅ PATRÓN OFICIAL FLET (flet-dev/flet/examples/controls/charts/pie_chart/example_2.py)
        - Itera TODAS las secciones en cada evento
        - NO filtra por tipo de evento
        - Llama update() al final
        """
        # Procesar TODAS las secciones (patrón oficial)
        for idx, section in enumerate(self._sections_ui):
            if idx == e.section_index:
                # Sección hovered
                section.radius = self._theme.hover_radius
                section.title_style = ft.TextStyle(
                    size=self._theme.title_size_hover,
                    color=get_chart_label_color(self._theme_mode),
                    weight=ft.FontWeight.BOLD,
                    shadow=ft.BoxShadow(blur_radius=2, color=ft.Colors.with_opacity(0.54, ft.Colors.ON_SURFACE)),
                )
                section.border_side = self._theme.hover_border
                
                # Mostrar tooltip
                self._update_center_info(idx)
                
                # Callback externo
                if self._on_hover_section:
                    self._on_hover_section(idx)
                
                # Highlight en leyenda (cada segmento tiene 3 textos: label, value, pct)
                for legend_idx, text in enumerate(self._legend_texts):
                    if legend_idx // 3 == idx:
                        text.weight = ft.FontWeight.BOLD
                    else:
                        text.weight = ft.FontWeight.NORMAL
            else:
                # Sección normal
                section.radius = self._theme.normal_radius
                section.title_style = ft.TextStyle(
                    size=self._theme.title_size_normal,
                    color=get_chart_label_color(self._theme_mode),
                    weight=ft.FontWeight.BOLD,
                )
                section.border_side = self._theme.normal_border
        
        # Si no hay sección (salió del gráfico), resetear
        if e.section_index is None:
            self._clear_center_info()
            for text in self._legend_texts:
                text.weight = ft.FontWeight.NORMAL
            if self._on_unhover:
                self._on_unhover()
        
        # Flet 0.80.5: los event handlers sincronizan automáticamente.
        # NO llamar update() aquí — VentasView orquesta page.update()
    
    def _update_center_info(self, index: int):
        """Actualizar información central (al hovear)"""
        if index >= len(self._snapshot.segments):
            return
        
        segment = self._snapshot.segments[index]
        controls = self._center_info_container.content.controls
        
        # [0] Nombre
        controls[0].value = segment.label
        # [1] Divider (no se toca)
        # [2] Valor en euros
        controls[2].value = format_eur(segment.value)
        
        # [3] Porcentaje
        controls[3].value = f"{segment.percentage:.1f}% of total"
        
        # [4] Ranking
        controls[4].value = f"#{index + 1} of {len(self._snapshot.segments)}"
        
        # Mostrar contenedor
        self._center_info_container.visible = True
    
    def _clear_center_info(self):
        """Limpiar información central (auto-update enabled)"""
        self._center_info_container.visible = False
    
    def _get_subtitle_text(self) -> str:
        """Generar texto de subtítulo con estadísticas"""
        total = sum(s.value for s in self._snapshot.segments)
        avg = total / len(self._snapshot.segments) if self._snapshot.segments else 0
        count = len(self._snapshot.segments)

        return f"Total: {format_eur(total)} | Products: {count} | Avg. per product: {format_eur(avg)}"
    
    def update_from_snapshot(self, new_snapshot: PieChartSnapshot):
        """
        Actualizar con nuevo snapshot (cambio de datos).
        Reconstruye la interfaz completa.
        """
        self._snapshot = new_snapshot
        # FIX #8: Limpiar estado antes de rebuild
        self._sections_ui = []
        self.content = self._build_ui()
    
    def update_theme(self, theme_mode):
        """
        Actualizar tema (light/dark).
        
        ✅ R7 COMPLIANCE: Solo mutación, sin llamar update().
                          VentasView orquesta page.update() después.
        """
        self._theme_mode = theme_mode
        self._palette = get_chart_palette(self._theme_mode)
        text_color = get_text_color(self._theme_mode)
        card_bg = get_card_color(self._theme_mode)
        
        # Mutar contenedor principal
        self.bgcolor = card_bg
        
        # Mutar colores en title
        if self._title_text:
            self._title_text.color = text_color
        
        # Mutar colores en subtitle
        if self._subtitle_text:
            self._subtitle_text.color = ft.Colors.with_opacity(0.7, text_color)
        
        # Mutar colores en secciones
        for idx, section in enumerate(self._sections_ui):
            if idx < len(self._snapshot.segments):
                segment = self._snapshot.segments[idx]
                section.color = self._palette[segment.color_index % len(self._palette)]
                section.title_style = ft.TextStyle(
                    size=self._theme.title_size_normal,
                    color=get_chart_label_color(self._theme_mode),
                    weight=ft.FontWeight.BOLD,
                )
                section.border_side = self._theme.normal_border
        
        # Mutar colores de badges (Top 3)
        badge_colors = [
            ft.Colors.PRIMARY,
            ft.Colors.SECONDARY,
            ft.Colors.TERTIARY,
        ]
        for idx, badge in enumerate(self._badge_containers):
            if idx < len(badge_colors):
                badge.bgcolor = badge_colors[idx]
                if badge.shadow:
                    badge.shadow.color = ft.Colors.with_opacity(0.3, ft.Colors.ON_SURFACE)
        for text in self._badge_texts:
            text.color = ft.Colors.ON_PRIMARY
        
        # Mutar colores en info de hover
        # Nueva estructura: [0]=Nombre, [1]=Divider, [2]=Valor€, [3]=%, [4]=Ranking
        if self._center_info_container and self._center_info_container.content:
            self._center_info_container.bgcolor = card_bg
            controls = self._center_info_container.content.controls
            if len(controls) >= 5:
                controls[0].color = text_color
                # controls[1] es Divider, no tiene .color
                controls[2].color = ft.Colors.PRIMARY
                controls[3].color = ft.Colors.with_opacity(0.75, text_color)
                controls[4].color = ft.Colors.SECONDARY

        # Mutar leyenda
        if self._legend_title_text:
            self._legend_title_text.color = text_color
        for text in self._legend_texts:
            text.color = text_color
        for idx, box in enumerate(self._legend_color_boxes):
            if idx < len(self._snapshot.segments):
                segment = self._snapshot.segments[idx]
                box.bgcolor = self._palette[segment.color_index % len(self._palette)]
        
        # ✅ R7: NO llamar self.update()
