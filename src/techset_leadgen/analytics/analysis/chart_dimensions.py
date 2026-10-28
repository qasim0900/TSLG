import math

# ------------------------------
# :: get Rod Width Function
# ------------------------------

"""
This module provides utility functions for determining chart dimensions based on the number of bars in a chart.
"""


def get_rod_width(bar_count: int) -> int:
    if bar_count <= 7:
        return 40
    elif bar_count <= 15:
        return 32
    elif bar_count <= 30:
        return 24
    elif bar_count <= 60:
        return 16
    elif bar_count <= 100:
        return 12
    else:
        return 8


# ---------------------------------
# :: get label interval Function
# ---------------------------------

"""
This module provides utility functions for determining chart dimensions based on the number of bars in a chart.
"""


def get_label_interval(bar_count: int) -> int:
    if bar_count <= 15:
        return 1
    elif bar_count <= 30:
        return 2
    elif bar_count <= 60:
        return 3
    elif bar_count <= 100:
        return 5
    else:
        return 10


# ------------------------------------
# :: Round to nice numbers Function
# ------------------------------------

"""
This module provides utility functions for determining chart dimensions based on the number of bars in a chart. 
"""


def round_to_nice_number(value: float) -> float:
    if value < 10:
        return 10.0
    magnitude = 10 ** math.floor(math.log10(value))
    normalized = value / magnitude
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
