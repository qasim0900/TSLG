"""
Modelo de datos único (AnalysisSnapshot) que representa TODO el estado analítico de la app.

Independiente de UI (Flet) y export (matplotlib/HTML).
Agnóstico respecto a cómo se generaron los datos.
Fácilmente serializable a JSON.

Este modelo es el "contrato" entre:
- Controllers (que lo generan)
- UI (que lo consume para Flet)
- Export (que lo consume para HTML)
"""

from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime, timezone
from enum import Enum


# ============================================================
# ENUMERACIONES
# ============================================================

class AnalysisMode(str, Enum):
    """Modo de análisis: normal o comparativo."""
    NORMAL = "normal"
    COMPARE = "compare"


class TimeGrouping(str, Enum):
    """Agrupación temporal para evolución."""
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


# ============================================================
# METADATOS
# ============================================================

@dataclass
class Metadata:
    """
    Metadatos generales del análisis.
    
    Campos:
    - mode: Modo de análisis (normal o compare)
    - grouping: Agrupación temporal usada en evolution
    - generated_at: Timestamp de generación
    - app_version: Versión de la app que generó este snapshot
    """
    mode: AnalysisMode
    grouping: TimeGrouping
    generated_at: datetime
    app_version: str = "1.0"


# ============================================================
# FILTROS
# ============================================================

@dataclass
class Filters:
    """
    Filtros que se aplicaron al análisis.
    
    Campos:
    - date_start: Fecha de inicio (YYYY-MM-DD)
    - date_end: Fecha de fin (YYYY-MM-DD)
    - client_name: Nombre del cliente (None = TODOS)
    - product_type: Tipo de producto (None = TODOS)
    
    Nota: Estos son los filtros DEL PERÍODO A.
          En compare, period_b tiene sus propios filtros.
    """
    date_start: str
    date_end: str
    client_name: Optional[str] = None
    product_type: Optional[str] = None


# ============================================================
# DATOS DE TABLA
# ============================================================

@dataclass
class TableRow:
    """
    Una fila de la tabla de productos.
    
    Campos:
    - product_type: Nombre del producto
    - quantity: Cantidad de transacciones
    - total_sales: Monto total en euros
    - avg_price: Precio promedio
    - min_price: Precio mínimo
    - max_price: Precio máximo
    """
    product_type: str
    quantity: int
    total_sales: float
    avg_price: float
    min_price: float
    max_price: float


# ============================================================
# MÉTRICAS
# ============================================================

@dataclass
class PeriodMetrics:
    """
    Métricas agregadas de un período.
    
    Campos:
    - total_sales: Monto total vendido (euros)
    - transactions: Cantidad de transacciones
    - avg_ticket: Ticket promedio (total_sales / transactions)
    - total_quantity: Cantidad de unidades
    - unique_clients: Cantidad de clientes distintos
    """
    total_sales: float
    transactions: int
    avg_ticket: float
    total_quantity: int
    unique_clients: int


# ============================================================
# EVOLUCIÓN TEMPORAL
# ============================================================

@dataclass
class EvolutionData:
    """
    Datos de evolución temporal (timeseries).
    
    Campos:
    - labels: Etiquetas temporales (ej: ["2024-01-01", "2024-01-02", ...])
    - values: Valores correspondientes (ventas por fecha/período)
    - grouping: Agrupación usada (day, week, month, etc.)
    
    Nota: En modo normal, esto es serie_a.
          En modo compare, se compara contra serie_b.
    """
    labels: List[str]
    values: List[float]
    grouping: TimeGrouping


# ============================================================
# DISTRIBUCIÓN DE PRODUCTOS
# ============================================================

@dataclass
class ProductDistribution:
    """
    Distribución de ventas por producto (para gráficos donut/barras).
    
    Campos:
    - labels: Nombres de productos
    - values: Montos de ventas
    - percentages: % del total
    
    Nota: Puede incluir TODOS los productos o TOP N (decisión en generación).
    """
    labels: List[str]
    values: List[float]
    percentages: List[float]


# ============================================================
# RANKING DE CLIENTES
# ============================================================

@dataclass
class ClientRank:
    """
    Un cliente en el ranking.
    
    Campos:
    - rank: Posición en ranking (1, 2, 3, ...)
    - client_name: Nombre del cliente
    - total_sales: Monto total vendido
    - transactions: Cantidad de transacciones
    - percentage_of_total: % del total de ventas
    """
    rank: int
    client_name: str
    total_sales: float
    transactions: int
    percentage_of_total: float


# ============================================================
# PERÍODO (A o B)
# ============================================================

@dataclass
class PeriodSnapshot:
    """
    Snapshot de datos de un período completo.
    
    Contiene todo lo necesario para:
    - Renderizar en Flet (UI normal)
    - Exportar en HTML (export)
    
    Campos:
    - label: Etiqueta para identificar el período ("Período Principal", "Período Comparación")
    - filters: Filtros aplicados a este período
    - table_data: Tabla de productos (todas las filas)
    - metrics: Métricas agregadas
    - evolution: Evolución temporal
    - product_distribution: Distribución de productos
    - top_clients: Top 5 clientes ordenados por total_sales
    """
    label: str
    filters: Filters
    table_data: List[TableRow]
    metrics: PeriodMetrics
    evolution: EvolutionData
    product_distribution: ProductDistribution
    top_clients: List[ClientRank]
    pie_chart: Optional["PieChartSnapshot"] = None
    evolution_raw: Optional[List[tuple]] = None  # Daily raw data for local regrouping (COMPARE only)


# ============================================================
# COMPARACIÓN (SOLO EN MODO COMPARE)
# ============================================================

@dataclass
class ComparisonMetrics:
    """
    Cambios entre período A y período B.
    
    Campos:
    - absolute_changes: Diferencias absolutas (B - A)
      - total_sales: Diferencia en euros
      - transactions: Diferencia en cantidad
      - avg_ticket: Diferencia en ticket promedio
      - total_quantity: Diferencia en cantidad
      - unique_clients: Diferencia en clientes
    
    - percentage_changes: Cambios porcentuales (% A → B)
      - (mismos campos, valores en %)
    """
    absolute_changes: dict  # {"total_sales": float, "transactions": int, ...}
    percentage_changes: dict  # {"total_sales": float, "transactions": float, ...}


# ============================================================
# V2: EVOLUCIÓN COMPARATIVA (CONTRATO NUEVO)
# ============================================================

@dataclass
class EvolutionPointV2:
    """
    Punto temporal enriquecido en evolución comparativa A vs B.
    
    Contiene toda la información necesaria para renderizar eje X,
    tooltips y exportes sin inferencias ni cálculos adicionales.
    
    Nota: grouping vive únicamente en snapshot.metadata.grouping,
          no se replica a nivel de punto.
    """
    key: str                 # Clave temporal canónica, ordenable (ej: "2024-03-01", "2024-W12", "2024-03", "2024-Q1", "2024")
    label: str               # Etiqueta legible (ej: "01 Mar", "Sem 12", "Mar 2024", "Q1 2024", "2024")
    start: datetime          # Inicio real del intervalo, UTC tz-aware (datetime.now(timezone.utc))
    end: datetime            # Fin real del intervalo, UTC tz-aware
    value_a: float           # Valor acumulado período A
    value_b: float           # Valor acumulado período B
    difference: float        # Diferencia B - A (para conveniencia UI/export)
    is_partial: bool = False # Intervalo truncado por filtros de fecha/cliente/producto


@dataclass
class EvolutionComparisonV2:
    """
    Comparación de evolución temporal V2 (contrato nuevo).
    
    Reemplaza EvolutionComparison con estructura de puntos enriquecidos.
    No incluye grouping (vive en snapshot.metadata.grouping únicamente).
    
    Garantías:
    - points está ordenado estrictamente por key
    - Todos los points tienen start < end
    - No hay solapamiento de intervalos
    """
    points: List[EvolutionPointV2]


@dataclass
class ProductComparison:
    """
    Comparación de distribución de productos entre A y B.
    
    Campos:
    - labels: Nombres de productos
    - series_a: Valores de A
    - series_b: Valores de B
    - differences: Diferencias (B - A)
    - percentage_diff: % de cambio
    """
    labels: List[str]
    series_a: List[float]
    series_b: List[float]
    differences: List[float]
    percentage_diff: List[float]


@dataclass
class ComparisonSnapshot:
    """
    Datos de comparación entre período A y período B.
    
    Nota: SOLO existe si mode == "compare".
    
    Campo `evolution` usa EvolutionComparisonV2 (modelo mejorado con metadata temporal).
    """
    metrics: ComparisonMetrics
    evolution: EvolutionComparisonV2  # Migración completada: V1 → V2
    products: ProductComparison

# ============================================================
# SNAPSHOTS VISUALES (NORMAL)
# ============================================================

@dataclass
class PieChartSegmentSnapshot:
    """
    Segmento visual del gráfico circular.

    Snapshot-only:
    - Sin lógica
    - Sin cálculos
    - Derivado de ProductDistribution
    """
    label: str
    value: float
    percentage: float
    color_index: int


@dataclass
class PieChartSnapshot:
    """
    Snapshot visual del gráfico circular (pie chart).

    Usado exclusivamente en modo NORMAL.
    """
    title: str
    segments: List[PieChartSegmentSnapshot]

# ============================================================
# SNAPSHOT RAÍZ
# ============================================================

@dataclass
class AnalysisSnapshot:
    """
    MODELO ÚNICO que representa TODO el estado analítico de la app.
    
    Puede serializarse a JSON y ser consumido por:
    - UI (Flet): renderiza gráficos, tablas, métricas
    - Export (HTML): genera reportes con gráficos matplotlib
    
    Estructura:
    - metadata: Información general
    - filters: Filtros aplicados (contexto del período A)
    - period_a: Snapshot del período principal (SIEMPRE presente)
    - period_b: Snapshot del período de comparación (SOLO si mode == "compare")
    - comparison: Datos de comparación (SOLO si mode == "compare")
    
    Ejemplo de acceso:
    
    # Modo normal:
    snapshot = AnalysisSnapshot(...)
    print(snapshot.period_a.metrics.total_sales)
    print(snapshot.period_a.evolution.values)
    assert snapshot.period_b is None
    assert snapshot.comparison is None
    
    # Modo compare:
    snapshot = AnalysisSnapshot(...)
    print(snapshot.period_a.metrics.total_sales)
    print(snapshot.period_b.metrics.total_sales)
    print(snapshot.comparison.metrics.percentage_changes["total_sales"])
    assert snapshot.period_b is not None
    assert snapshot.comparison is not None
    """
    metadata: Metadata
    filters: Filters
    period_a: PeriodSnapshot
    period_b: Optional[PeriodSnapshot] = None
    comparison: Optional[ComparisonSnapshot] = None

    def is_normal_mode(self) -> bool:
        """Retorna True si es modo normal."""
        return self.metadata.mode == AnalysisMode.NORMAL

    def is_compare_mode(self) -> bool:
        """Retorna True si es modo compare."""
        return self.metadata.mode == AnalysisMode.COMPARE

    def validate(self) -> bool:
        """
        Valida consistencia del snapshot.
        
        Lanza: ValueError si hay inconsistencias
        Retorna: True si es válido
        
        Validaciones en NORMAL mode:
        - period_b y comparison deben ser None
        
        Validaciones en COMPARE mode:
        - period_b y comparison deben existir
        - comparison.evolution.points no vacío
        - Todos los start/end son tz-aware UTC
        - start < end en cada punto
        - No solapamiento: points[i].end <= points[i+1].start
        - difference == value_b - value_a
        - key válida según grouping
        - points ordenados estrictamente por key
        """
        if self.is_normal_mode():
            if self.period_b is not None:
                raise ValueError("NORMAL mode: period_b must be None")
            if self.comparison is not None:
                raise ValueError("NORMAL mode: comparison must be None")
        
        elif self.is_compare_mode():
            if self.period_b is None:
                raise ValueError("COMPARE mode: period_b must not be None")
            if self.comparison is None:
                raise ValueError("COMPARE mode: comparison must not be None")
            
            # ================================================================
            # VALIDAR ESTRUCTURA DE EVOLUTION.POINTS
            # ================================================================
            
            evolution = self.comparison.evolution
            
            if not hasattr(evolution, 'points'):
                raise ValueError("comparison.evolution has no attribute 'points'")
            
            if not isinstance(evolution.points, list):
                raise ValueError(f"comparison.evolution.points must be a list, got {type(evolution.points)}")
            
            if len(evolution.points) == 0:
                raise ValueError("comparison.evolution.points cannot be empty")
            
            # ================================================================
            # VALIDAR CADA PUNTO
            # ================================================================
            
            prev_key = None
            
            for idx, point in enumerate(evolution.points):
                # Validar campos obligatorios
                required_fields = ['key', 'label', 'start', 'end', 'value_a', 'value_b', 'difference', 'is_partial']
                for field in required_fields:
                    if not hasattr(point, field):
                        raise ValueError(f"Point[{idx}] missing field '{field}'")
                
                # Validar que start y end son datetime con timezone UTC
                if not isinstance(point.start, datetime):
                    raise ValueError(f"Point[{idx}].start must be a datetime, got {type(point.start)}")
                if not isinstance(point.end, datetime):
                    raise ValueError(f"Point[{idx}].end must be a datetime, got {type(point.end)}")
                
                if point.start.tzinfo is None:
                    raise ValueError(f"Point[{idx}].start must be timezone-aware, got a naive datetime")
                if point.end.tzinfo is None:
                    raise ValueError(f"Point[{idx}].end must be timezone-aware, got a naive datetime")
                
                if point.start.tzinfo != timezone.utc:
                    raise ValueError(f"Point[{idx}].start timezone must be UTC, got {point.start.tzinfo}")
                if point.end.tzinfo != timezone.utc:
                    raise ValueError(f"Point[{idx}].end timezone must be UTC, got {point.end.tzinfo}")
                
                # Validar start < end
                if point.start >= point.end:
                    raise ValueError(f"Point[{idx}]: start ({point.start}) must be < end ({point.end})")
                
                # Validar que difference == value_b - value_a
                expected_diff = point.value_b - point.value_a
                if abs(point.difference - expected_diff) > 1e-9:  # Tolerancia numérica
                    raise ValueError(
                        f"Point[{idx}]: difference ({point.difference}) != "
                        f"value_b ({point.value_b}) - value_a ({point.value_a}) ({expected_diff})"
                    )
                
                # Validar key según grouping
                self._validate_key_format(point.key, self.metadata.grouping, idx)
                
                # Validar ordenamiento estricto por key
                if prev_key is not None:
                    if point.key <= prev_key:
                        raise ValueError(
                            f"Point[{idx}]: key '{point.key}' must be > previous key '{prev_key}' (not strictly ordered)"
                        )
                prev_key = point.key
            
            # ================================================================
            # VALIDAR NO SOLAPAMIENTO
            # ================================================================
            
            for idx in range(len(evolution.points) - 1):
                current = evolution.points[idx]
                next_point = evolution.points[idx + 1]
                
                if current.end > next_point.start:
                    raise ValueError(
                        f"Points[{idx}] and [{idx + 1}] overlap: "
                        f"end[{idx}] ({current.end}) > start[{idx + 1}] ({next_point.start})"
                    )
        
        return True
    
    def _validate_key_format(self, key: str, grouping: TimeGrouping, point_idx: int) -> None:
        """
        Valida que la key cumpla el formato esperado para el grouping.
        
        Lanza: ValueError si la key es inválida
        """
        import re
        
        if grouping == TimeGrouping.DAY:
            # Formato: YYYY-MM-DD
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', key):
                raise ValueError(f"Point[{point_idx}]: DAY key '{key}' must use the format YYYY-MM-DD")
            try:
                datetime.strptime(key, "%Y-%m-%d")
            except ValueError:
                raise ValueError(f"Point[{point_idx}]: DAY key '{key}' is not a valid date")
        
        elif grouping == TimeGrouping.WEEK:
            # Formato: YYYY-Www (ISO week)
            if not re.match(r'^\d{4}-W\d{2}$', key):
                raise ValueError(f"Point[{point_idx}]: WEEK key '{key}' must use the format YYYY-Www")
            try:
                parts = key.split('-W')
                int(parts[0])
                week = int(parts[1])
                if not (1 <= week <= 53):
                    raise ValueError(f"Week {week} out of range 1-53")
            except (ValueError, IndexError) as e:
                raise ValueError(f"Point[{point_idx}]: WEEK key '{key}' is invalid: {e}")
        
        elif grouping == TimeGrouping.MONTH:
            # Formato: YYYY-MM
            if not re.match(r'^\d{4}-\d{2}$', key):
                raise ValueError(f"Point[{point_idx}]: MONTH key '{key}' must use the format YYYY-MM")
            try:
                datetime.strptime(key, "%Y-%m")
            except ValueError:
                raise ValueError(f"Point[{point_idx}]: MONTH key '{key}' is not valid")
        
        elif grouping == TimeGrouping.QUARTER:
            # Formato: YYYY-Qn
            if not re.match(r'^\d{4}-Q[1-4]$', key):
                raise ValueError(f"Point[{point_idx}]: QUARTER key '{key}' must use the format YYYY-Qn where n is 1-4")
        
        elif grouping == TimeGrouping.YEAR:
            # Formato: YYYY
            if not re.match(r'^\d{4}$', key):
                raise ValueError(f"Point[{point_idx}]: YEAR key '{key}' must use the format YYYY")
            try:
                int(key)
            except ValueError:
                raise ValueError(f"Point[{point_idx}]: YEAR key '{key}' is not a valid year")
