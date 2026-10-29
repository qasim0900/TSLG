import base64
import io
import textwrap
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib import rcParams
from matplotlib.ticker import FuncFormatter, MaxNLocator

rcParams['font.family'] = 'sans-serif'
rcParams['font.sans-serif'] = ['Inter', 'Arial', 'Helvetica', 'DejaVu Sans']
rcParams['axes.titleweight'] = 'bold'
rcParams['axes.labelweight'] = 'bold'
rcParams['axes.titlesize'] = 15
rcParams['axes.labelsize'] = 12
rcParams['xtick.labelsize'] = 11
rcParams['ytick.labelsize'] = 11


def _subplots(*, figsize: tuple[float, float]):
    figure = Figure(figsize=figsize)
    FigureCanvasAgg(figure)
    return figure, figure.subplots()


def _truncate(text: str, max_len: int = 28) -> str:
    if text is None:
        return ""
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - 1)].rstrip() + "…"


def _wrap_label(text: str, width: int = 18, max_lines: int = 2) -> str:
    text = str(text or "").strip()
    wrapped = textwrap.wrap(text, width=width) or [""]
    if len(wrapped) <= max_lines:
        return "\n".join(wrapped)
    kept = wrapped[:max_lines]
    kept[-1] = _truncate(kept[-1], max(4, width))
    return "\n".join(kept)


def _format_eur(value: float) -> str:
    try:
        return f"€{float(value):,.0f}"
    except (TypeError, ValueError):
        return f"€{value}"


def _eur_formatter(_x, _pos):
    return _format_eur(_x)


def _get_base64_image(fig):
    buffer = io.BytesIO()
    fig.savefig(
        buffer,
        format='png',
        bbox_inches='tight',
        dpi=220,
        facecolor='white',
    )
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode()
    buffer.close()
    fig.clear()
    return image_base64

def _configure_time_axis(ax, labels: list[str]):
    num_points = len(labels)
    step = max(1, num_points // 8)

    xticks = list(range(0, num_points, step))
    if (num_points - 1) not in xticks:
        xticks.append(num_points - 1)

    xticklabels = [labels[i] if i < num_points else "" for i in xticks]

    ax.set_xticks(xticks)
    ax.set_xticklabels(
        xticklabels,
        fontsize=10,
        rotation=45,
        ha='right'
    )


def _configure_common_axes(ax, ylabel: str):
    ax.set_xlabel('Period', fontsize=12, fontweight='bold')
    ax.set_ylabel(ylabel, fontsize=12, fontweight='bold')

    ax.grid(True, alpha=0.25, linestyle='--', zorder=0)
    ax.set_axisbelow(True)

    ax.yaxis.set_major_formatter(FuncFormatter(_eur_formatter))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6))

def generate_pie_chart(labels, values, title=None, percentages=None):
    fig, ax = _subplots(figsize=(8.4, 4.8))

    colors = ['#39B54A', '#FFCB4A', '#FF6F00', '#C62828', '#6A1B9A', '#00796B']
    colors = colors[:len(labels)]

    if percentages is None:
        total = float(sum(values)) if values else 0.0
        percentages = [
            (float(val) / total * 100.0) if total else 0.0
            for val in values
        ]

    def autopct_fn(pct):
        return f"{pct:.1f}%" if pct >= 3 else ""

    legend_labels = []
    for lab, val, pct in zip(labels, values, percentages):
        legend_labels.append(f"{_truncate(lab, 26)} — {pct:.1f}% ({_format_eur(val)})")

    wedges, _texts, autotexts = ax.pie(
        values,
        labels=None,
        autopct=autopct_fn,
        colors=colors,
        startangle=90,
        pctdistance=0.72,
        textprops={'fontsize': 12, 'fontweight': 'bold'},
        wedgeprops=dict(width=0.45, edgecolor='white', linewidth=1.0),
        radius=0.71,
    )

    if title:
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)

    ax.legend(
        wedges,
        legend_labels,
        loc='upper center',
        bbox_to_anchor=(0.5, -0.04),
        frameon=False,
        fontsize=10.5,
        handlelength=1.2,
        labelspacing=0.7,
        ncol=2,
        columnspacing=1.2,
    )
    ax.set(aspect='equal')
    fig.subplots_adjust(top=0.98, bottom=0.02, left=0.05, right=0.95)

    return _get_base64_image(fig)


def generate_bar_chart(labels, values, title="Bar chart", ylabel="Value"):
    fig, ax = _subplots(figsize=(10.5, 6.5))

    colors = ['#39B54A', '#FFCB4A', '#FF6F00', '#C62828', '#6A1B9A']
    colors = colors[:len(labels)]

    bars = ax.bar(range(len(labels)), values, color=colors, edgecolor='#333', linewidth=1.5)

    for bar in bars:
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width()/2.,
            height,
            f'{height:,.0f}',
            ha='center',
            va='bottom',
            fontsize=9,
            fontweight='bold'
        )

    ax.set_xlabel('Product', fontsize=11, fontweight='bold')
    ax.set_ylabel(ylabel, fontsize=11, fontweight='bold')
    ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels([_truncate(l, 18) for l in labels], rotation=45, ha='right')
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))

    fig.tight_layout()
    return _get_base64_image(fig)


def generate_horizontal_bar_chart(labels, values, title=None, xlabel="Sales (€)"):
    fig, ax = _subplots(figsize=(12.0, 7.6))

    base_colors = ['#39B54A', '#32CD32', '#2F9E44', '#238636', '#176B2C']
    colors = (base_colors * ((len(labels) // len(base_colors)) + 1))[:len(labels)]

    clean_labels = [_wrap_label(l, width=20, max_lines=2) for l in labels]
    bars = ax.barh(range(len(clean_labels)), values, color=colors, edgecolor='#1f1f1f', linewidth=1.0)

    max_val = float(max(values)) if values else 0.0
    for bar in bars:
        width = float(bar.get_width())
        ax.text(
            width,
            bar.get_y() + bar.get_height()/2.,
            f"  {_format_eur(width)}",
            ha='left',
            va='center',
            fontsize=10,
            fontweight='bold',
            color='#111',
        )

    ax.set_ylabel('')
    ax.set_xlabel(xlabel, fontsize=11, fontweight='bold')
    if title:
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
    ax.set_yticks(range(len(clean_labels)))
    ax.set_yticklabels(clean_labels, fontsize=12, fontweight='bold')
    ax.invert_yaxis()
    ax.grid(axis='x', alpha=0.25, linestyle='--')
    ax.xaxis.set_major_formatter(FuncFormatter(_eur_formatter))
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.set_xlim(0, max_val * 1.18 if max_val else 1)

    fig.subplots_adjust(left=0.28, right=0.98, top=0.92, bottom=0.16)

    return _get_base64_image(fig)


def generate_evolution_line_chart(evolution_points) -> str:
    if not evolution_points:
        raise ValueError("evolution_points cannot be empty")

    try:
        labels = [p.label for p in evolution_points]
        values_a = [p.value_a for p in evolution_points]
        values_b = [p.value_b for p in evolution_points]
    except AttributeError as e:
        raise ValueError(f"evolution_points has items missing required attributes (label, value_a, value_b): {e}")

    fig, ax = _subplots(figsize=(12.0, 5.0))

    x_pos = list(range(len(labels)))

    ax.plot(
        x_pos,
        values_a,
        color='#39B54A',
        marker='o',
        markersize=6,
        linewidth=2.5,
        label='Period A',
        zorder=3,
    )

    ax.plot(
        x_pos,
        values_b,
        color='#FF9800',
        marker='s',
        markersize=6,
        linewidth=2.5,
        label='Period B',
        zorder=2,
    )

    _configure_time_axis(ax, labels)
    _configure_common_axes(
        ax,
        ylabel="Value (€)",
    )

    ax.legend(loc='best', fontsize=11, framealpha=0.95)

    fig.subplots_adjust(left=0.12, right=0.98, top=0.92, bottom=0.20)
    return _get_base64_image(fig)

def generate_evolution_bar_chart(
    labels: list[str],
    values: list[float],
) -> str:
    if not labels or not values:
        raise ValueError("labels and values cannot be empty")

    if len(labels) != len(values):
        raise ValueError(f"labels ({len(labels)}) and values ({len(values)}) have different lengths")

    fig, ax = _subplots(figsize=(12.0, 5.0))
    x_pos = list(range(len(labels)))

    ax.bar(
        x_pos,
        values,
        color='#39B54A',
        edgecolor='#176B2C',
        linewidth=1.0,
        width=0.7
    )

    _configure_time_axis(ax, labels)
    _configure_common_axes(ax, ylabel="Sales (€)")

    fig.subplots_adjust(left=0.12, right=0.98, top=0.92, bottom=0.20)
    return _get_base64_image(fig)


def generate_compare_bar_chart(labels, values_a, values_b, title="A vs. B comparison"):
    fig, ax = _subplots(figsize=(10.5, 6.0))

    x = range(len(labels))
    width = 0.35

    ax.bar(
        [i - width / 2 for i in x],
        values_a,
        width,
        label="Period A",
        color="#39B54A",
    )

    ax.bar(
        [i + width / 2 for i in x],
        values_b,
        width,
        label="Period B",
        color="#FF9800",
    )

    ax.set_ylabel("Value")
    ax.set_title(title, fontsize=14, fontweight="bold", pad=20)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=11, fontweight="bold")
    ax.legend()

    ax.grid(axis="y", alpha=0.3, linestyle="--")
    fig.tight_layout()

    return _get_base64_image(fig)

