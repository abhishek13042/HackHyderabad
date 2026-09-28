"""The learning curve as a standalone SVG: no plotting library, byte-for-byte reproducible."""

from collections.abc import Sequence
from typing import Any
from xml.sax.saxutils import escape

WIDTH, HEIGHT = 640, 340
LEFT, RIGHT, TOP, BOTTOM = 56, 24, 40, 56
ON, OFF, AUTO, INK, GRID = "#0f766e", "#b45309", "#99f6e4", "#1f2937", "#e5e7eb"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def month_label(period: str) -> str:
    year, month = period.split("-")
    return f"{MONTHS[int(month) - 1]} {year}"


def learning_curve_svg(points: Sequence[dict[str, Any]]) -> str:
    """Bars: share auto-resolved (ON). Lines: action accuracy with memory ON and OFF."""
    plot_w, plot_h = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM
    step = plot_w / max(len(points), 1)

    def x(i: int) -> float:
        return LEFT + step * (i + 0.5)

    def y(value: float) -> float:
        return TOP + plot_h * (1 - value)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="system-ui, sans-serif" font-size="12">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#ffffff"/>',
        f'<text x="{LEFT}" y="22" font-size="14" font-weight="600" fill="{INK}">'
        "Suggestion accuracy per month, memory ON vs OFF</text>",
    ]
    for tick in range(0, 101, 25):
        ty = y(tick / 100)
        parts.append(
            f'<line x1="{LEFT}" y1="{ty:.1f}" x2="{WIDTH - RIGHT}" y2="{ty:.1f}" stroke="{GRID}"/>'
        )
        parts.append(
            f'<text x="{LEFT - 8}" y="{ty + 4:.1f}" text-anchor="end" fill="{INK}">{tick}%</text>'
        )
    bar_w = step * 0.45
    for i, p in enumerate(points):
        if (auto := p.get("auto_rate")) is not None and auto > 0:
            parts.append(
                f'<rect x="{x(i) - bar_w / 2:.1f}" y="{y(auto):.1f}" width="{bar_w:.1f}" '
                f'height="{plot_h * auto:.1f}" fill="{AUTO}"/>'
            )
        parts.append(
            f'<text x="{x(i):.1f}" y="{HEIGHT - BOTTOM + 18}" text-anchor="middle" '
            f'fill="{INK}">{escape(month_label(p["period"]))}</text>'
        )
    for key, color in (("accuracy_off", OFF), ("accuracy_on", ON)):
        coords = [(x(i), y(p[key])) for i, p in enumerate(points) if p.get(key) is not None]
        if len(coords) > 1:
            path = " ".join(f"{cx:.1f},{cy:.1f}" for cx, cy in coords)
            parts.append(
                f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2.5"/>'
            )
        parts += [
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="{color}"/>' for cx, cy in coords
        ]
    legend = (("Memory ON", ON), ("Memory OFF", OFF), ("Auto-resolved (ON)", AUTO))
    for n, (text, color) in enumerate(legend):
        lx = LEFT + n * 170
        ly = HEIGHT - 16
        parts.append(f'<rect x="{lx}" y="{ly - 10}" width="12" height="12" fill="{color}"/>')
        parts.append(f'<text x="{lx + 18}" y="{ly}" fill="{INK}">{text}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
