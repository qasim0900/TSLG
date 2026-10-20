# analysis/chart_dimensions.py
"""
Cálculos matemáticos puros para dimensiones y densidad de gráficos.

Estos helpers NO dependen de Flet ni theme.
Se usan en grafico_evolucion.py para adaptar visualmente según cantidad de datos.
"""

import math


def get_rod_width(bar_count: int) -> int:
    """
    Ajusta ancho de barra según densidad de datos.
    
    Desktop optimal: barras visibles sin colapsar el layout.
    
    Args:
        bar_count: Número de barras a renderizar
    
    Returns:
        Ancho en pixels (8-40px)
    
    Ejemplos:
        get_rod_width(5) → 40
        get_rod_width(25) → 24
        get_rod_width(70) → 16
    """
    if bar_count <= 7:
        return 40  # Barras anchas para datasets pequeños
    elif bar_count <= 15:
        return 32
    elif bar_count <= 30:
        return 24  # Sweet spot - balance visual/densidad
    elif bar_count <= 60:
        return 16
    elif bar_count <= 100:
        return 12  # Mínimo recomendado para legibilidad
    else:
        return 8   # Límite inferior - datasets masivos


def get_label_interval(bar_count: int) -> int:
    """
    Calcula cada cuántas barras mostrar etiqueta del eje X.
    
    Previene superposición de etiquetas con datasets densos.
    Basado en legibilidad Desktop (mínimo ~40px por etiqueta).
    
    Args:
        bar_count: Número total de barras
    
    Returns:
        Intervalo (1=todas, 2=cada 2da, etc.)
    
    Ejemplos:
        get_label_interval(10) → 1 (mostrar todas)
        get_label_interval(25) → 2 (cada 2da)
        get_label_interval(80) → 5 (cada 5ta)
    """
    if bar_count <= 15:
        return 1  # Mostrar todas
    elif bar_count <= 30:
        return 2  # 1 de cada 2
    elif bar_count <= 60:
        return 3  # 1 de cada 3
    elif bar_count <= 100:
        return 5  # 1 de cada 5
    else:
        return 10  # 1 de cada 10 - dataset masivo


def round_to_nice_number(value: float) -> float:
    """
    Redondea max_y a número 'bonito' para el eje.
    
    Mejora legibilidad del eje Y con valores redondeados.
    Usa serie: 1.5, 2.0, 2.5, 5.0, 10.0 (múltiplos de magnitud).
    
    Args:
        value: Valor crudo calculado
    
    Returns:
        Valor redondeado al siguiente múltiplo 'bonito'
    
    Ejemplos:
        round_to_nice_number(87) → 100.0
        round_to_nice_number(234) → 250.0
        round_to_nice_number(1567) → 2000.0
        round_to_nice_number(12345) → 15000.0
    """
    if value < 10:
        return 10.0
    
    # Calcular orden de magnitud
    magnitude = 10 ** math.floor(math.log10(value))
    
    # Normalizar a rango 1.0 - 10.0
    normalized = value / magnitude
    
    # Redondear a valor 'bonito' (serie: 1.5, 2.0, 2.5, 5.0, 10.0)
    if normalized <= 1.5:
        rounded = 1.5
    elif normalized <= 2.0:
        rounded = 2.0
    elif normalized <= 2.5:
        rounded = 2.5
    elif normalized <= 5.0:
        rounded = 5.0
    else:
        rounded = 10.0
    
    return rounded * magnitude
