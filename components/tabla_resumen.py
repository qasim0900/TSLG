"""Tabla resumen de ventas agrupadas por producto."""
import flet as ft
from utils.formatting import format_eur_no_symbol
from utils.ui_dispatch import mounted_page


class TablaResumen(ft.DataTable):
    def __init__(self, rows, columns=None):
        self._raw_rows = rows if rows else []

        self._columns = columns if columns else [
            "Product",
            "Total sales (€)",
            "# Sales",
            "Average price (€)",
            "Min. price (€)",
            
            "Max. price (€)",
        ]

        self._sort_column_index = None
        self._sort_ascending = True

        # ✅ COLUMNA PLACEHOLDER (OBLIGATORIA)
        super().__init__(
            columns=[
                ft.DataColumn(ft.Text(""))  # ← evita crash antes de did_mount
            ],
            rows=[],
            column_spacing=20,
            divider_thickness=0,
            heading_row_height=52,
        )

    # -------------------------------------------------
    # Lifecycle
    # -------------------------------------------------
    def did_mount(self):
        self._build_columns()
        self._build_rows()
        self._apply_theme()
        self.update()
    # -------------------------------------------------
    # Columns
    # -------------------------------------------------
    def _build_columns(self):
        self.columns = [
            ft.DataColumn(
                ft.Text(
                    col,
                    weight=ft.FontWeight.BOLD,
                    no_wrap=True,
                    text_align=ft.TextAlign.RIGHT if i > 0 else ft.TextAlign.LEFT,
                ),
                numeric=(i > 0),
                on_sort=self._on_sort_requested,
            )
            for i, col in enumerate(self._columns)
        ]

    # -------------------------------------------------
    # Rows
    # -------------------------------------------------
    def _build_rows(self):
        rows = []

        for row in self._raw_rows:
            cells = []

            for i, value in enumerate(row[:len(self._columns)]):
                if isinstance(value, int) and not isinstance(value, bool):
                    cell = ft.Text(f"{value:,}", text_align=ft.TextAlign.RIGHT)
                elif isinstance(value, float):
                    formatted = format_eur_no_symbol(value)
                    cell = ft.Text(formatted, text_align=ft.TextAlign.RIGHT)
                else:
                    cell = ft.Text(str(value), text_align=ft.TextAlign.LEFT)

                cells.append(ft.DataCell(cell))

            rows.append(ft.DataRow(cells=cells))

        self.rows = rows

    # -------------------------------------------------
    # Sorting
    # -------------------------------------------------
    def _on_sort_requested(self, e: ft.ControlEvent):
        index = int(e.column_index)
        ascending = (
            e.ascending == "true"
            if isinstance(e.ascending, str)
            else bool(e.ascending)
        )

        normal = [r for r in self._raw_rows if r[0] != "TOTAL"]
        total = [r for r in self._raw_rows if r[0] == "TOTAL"]

        def key(row):
            value = row[index]
            if isinstance(value, (int, float)):
                return value
            if value is None:
                return ""
            return str(value).lower()

        normal.sort(key=key, reverse=not ascending)
        self._raw_rows = normal + total

        self.sort_column_index = index
        self.sort_ascending = ascending

        self._build_rows()

    # -------------------------------------------------
    # Theme
    # -------------------------------------------------
    def _apply_theme(self):
        if not mounted_page(self):
            return

        self.heading_row_color = (
            ft.Colors.with_opacity(0.08, ft.Colors.SURFACE)
            if self.page.theme_mode == ft.ThemeMode.DARK
            else ft.Colors.with_opacity(0.06, ft.Colors.SURFACE)
        )

    def update_theme(self, theme_mode):
        """Actualiza colores de tabla según el tema.

        ✅ R9 CONFORME: Muta heading_row_color sin llamar self.update().
        El caller (VentasView) es responsable de page.update() (R7).
        """
        self.heading_row_color = (
            ft.Colors.with_opacity(0.08, ft.Colors.SURFACE)
            if theme_mode == ft.ThemeMode.DARK
            else ft.Colors.with_opacity(0.06, ft.Colors.SURFACE)
        )
        # ❌ NO llamar self.update() — R7: caller hace page.update()
