"""Small SVG charts for the reports.

Deliberately few forms: horizontal bars for magnitude, a single stacked bar for
composition, a treemap for size-within-hierarchy, and stat tiles for headline
numbers. Every series is direct-labelled, so identity never rests on colour
alone, and categorical hues are assigned in fixed order and never cycled.
"""

from __future__ import annotations

import html
import math
from typing import Dict, List, Optional, Sequence, Tuple

from . import theme

Item = Tuple[str, float]


def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def _fmt(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def fold_other(items: Sequence[Item], limit: int = 8) -> List[Item]:
    """Keep the top ``limit`` entries and sum the rest into 'Other'."""
    ordered = sorted(items, key=lambda kv: -kv[1])
    if len(ordered) <= limit:
        return list(ordered)
    head = ordered[: limit - 1]
    rest = sum(value for _, value in ordered[limit - 1 :])
    return head + [(f"Other ({len(ordered) - limit + 1})", rest)]


def bar_chart(items: Sequence[Item], *, title: str = "", width: float = 520,
              row_height: float = 26, label_width: float = 150, unit: str = "",
              colour: Optional[str] = None, colours: Optional[Sequence[str]] = None) -> str:
    """Horizontal bars — the default for 'compare magnitudes across categories'."""
    data = [(str(k), float(v)) for k, v in items if v is not None]
    if not data:
        return _empty(width, 60, "No data")
    top = max(value for _, value in data) or 1.0
    header = 30 if title else 8
    height = header + len(data) * row_height + 12
    bar_area = width - label_width - 74
    parts = [_open(width, height, title)]
    for index, (label, value) in enumerate(data):
        y = header + index * row_height
        fill = colours[index] if colours else (colour or theme.series_color(index))
        bar_w = max(2.0, bar_area * (value / top))
        parts.append(
            f'<text x="0" y="{y + row_height / 2 + 4:.1f}" font-family="{theme.FONT}" font-size="11.5" '
            f'fill="{theme.INK}">{esc(_clip(label, 24))}</text>'
        )
        parts.append(
            f'<rect x="{label_width}" y="{y + 4:.1f}" width="{bar_w:.1f}" height="{row_height - 12:.1f}" '
            f'rx="4" fill="{fill}"/>'
        )
        parts.append(
            f'<text x="{label_width + bar_w + 8:.1f}" y="{y + row_height / 2 + 4:.1f}" '
            f'font-family="{theme.FONT}" font-size="11" fill="{theme.MUTED}">{_fmt(value)}{esc(unit)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def stacked_bar(items: Sequence[Item], *, title: str = "", width: float = 520,
                height: float = 84, colours: Optional[Dict[str, str]] = None,
                legend: bool = True) -> str:
    """One stacked bar for composition, with a 2px gap between segments."""
    data = [(str(k), float(v)) for k, v in items if v]
    total = sum(value for _, value in data)
    if not data or total <= 0:
        return _empty(width, 60, "No data")
    header = 28 if title else 6
    bar_y = header
    bar_h = 26.0
    parts = [_open(width, height + header, title)]
    x = 0.0
    gap = 2.0
    usable = width - gap * (len(data) - 1)
    for index, (label, value) in enumerate(data):
        segment = usable * (value / total)
        fill = (colours or {}).get(label) or theme.series_color(index)
        radius = 4 if index in (0, len(data) - 1) else 0
        parts.append(
            f'<rect x="{x:.1f}" y="{bar_y}" width="{max(segment, 1.5):.1f}" height="{bar_h}" '
            f'rx="{radius}" fill="{fill}"/>'
        )
        if segment > 44:
            parts.append(
                f'<text x="{x + segment / 2:.1f}" y="{bar_y + bar_h / 2 + 4:.1f}" text-anchor="middle" '
                f'font-family="{theme.FONT}" font-size="11" font-weight="600" fill="#ffffff">'
                f"{_fmt(value)}</text>"
            )
        x += segment + gap
    if legend:
        legend_y = bar_y + bar_h + 22
        lx = 0.0
        for index, (label, value) in enumerate(data):
            fill = (colours or {}).get(label) or theme.series_color(index)
            text = f"{label} {_fmt(value)}"
            parts.append(
                f'<rect x="{lx:.1f}" y="{legend_y - 9}" width="10" height="10" rx="2.5" fill="{fill}"/>'
                f'<text x="{lx + 15:.1f}" y="{legend_y}" font-family="{theme.FONT}" font-size="11" '
                f'fill="{theme.MUTED}">{esc(text)}</text>'
            )
            lx += 28 + len(text) * 6.1
            if lx > width - 80:
                lx = 0.0
                legend_y += 18
    parts.append("</svg>")
    return "".join(parts)


def treemap(items: Sequence[Item], *, title: str = "", width: float = 640, height: float = 320,
            unit: str = "") -> str:
    """Squarified treemap — size within a flat hierarchy."""
    data = [(str(k), float(v)) for k, v in items if v and v > 0]
    if not data:
        return _empty(width, 80, "No data")
    data.sort(key=lambda kv: -kv[1])
    header = 28 if title else 6
    rects = _squarify(data, 0.0, 0.0, width, height)
    parts = [_open(width, height + header, title), f'<g transform="translate(0,{header})">']
    for index, (label, value, x, y, w, h) in enumerate(rects):
        fill = theme.series_color(index)
        parts.append(
            f'<rect x="{x + 1:.1f}" y="{y + 1:.1f}" width="{max(w - 2, 1):.1f}" '
            f'height="{max(h - 2, 1):.1f}" rx="4" fill="{fill}" fill-opacity="0.92"/>'
        )
        if w > 62 and h > 30:
            parts.append(
                f'<text x="{x + 9:.1f}" y="{y + 20:.1f}" font-family="{theme.FONT}" font-size="11.5" '
                f'font-weight="600" fill="#ffffff">{esc(_clip(label, int(w / 7)))}</text>'
                f'<text x="{x + 9:.1f}" y="{y + 35:.1f}" font-family="{theme.FONT}" font-size="10.5" '
                f'fill="#ffffff" fill-opacity="0.85">{_fmt(value)}{esc(unit)}</text>'
            )
    parts.append("</g></svg>")
    return "".join(parts)


def _squarify(data: Sequence[Item], x: float, y: float, width: float, height: float
              ) -> List[Tuple[str, float, float, float, float, float]]:
    out: List[Tuple[str, float, float, float, float, float]] = []
    items = list(data)
    cx, cy, cw, ch = x, y, width, height
    while items:
        row: List[Item] = []
        remaining = sum(value for _, value in items) or 1.0
        side = min(cw, ch)
        best = float("inf")
        while items:
            candidate = row + [items[0]]
            ratio = _worst_ratio(candidate, remaining, side, cw, ch)
            if ratio > best and row:
                break
            best = ratio
            row.append(items.pop(0))
        row_total = sum(value for _, value in row)
        fraction = row_total / remaining if remaining else 0
        if cw >= ch:
            row_w = cw * fraction
            offset = cy
            for label, value in row:
                share = (value / row_total) if row_total else 0
                out.append((label, value, cx, offset, row_w, ch * share))
                offset += ch * share
            cx += row_w
            cw -= row_w
        else:
            row_h = ch * fraction
            offset = cx
            for label, value in row:
                share = (value / row_total) if row_total else 0
                out.append((label, value, offset, cy, cw * share, row_h))
                offset += cw * share
            cy += row_h
            ch -= row_h
    return out


def _worst_ratio(row: Sequence[Item], remaining: float, side: float, w: float, h: float) -> float:
    total = sum(value for _, value in row)
    if not total or not side:
        return float("inf")
    area = (total / remaining) * (w * h)
    if area <= 0:
        return float("inf")
    length = area / side
    worst = 0.0
    for _, value in row:
        share = (value / total) * area
        thickness = share / length if length else 0
        if thickness <= 0:
            return float("inf")
        worst = max(worst, max(length / thickness, thickness / length))
    return worst


def stat_tiles(tiles: Sequence[Tuple[str, str, str]], *, width: float = 640,
               columns: int = 4) -> str:
    """Headline numbers: (value, label, accent colour)."""
    rows = math.ceil(len(tiles) / columns) or 1
    tile_w = width / columns
    tile_h = 76.0
    parts = [_open(width, rows * tile_h, "")]
    for index, (value, label, colour) in enumerate(tiles):
        col = index % columns
        row = index // columns
        x = col * tile_w
        y = row * tile_h
        parts.append(
            f'<rect x="{x + 3:.1f}" y="{y + 3:.1f}" width="{tile_w - 8:.1f}" height="{tile_h - 10:.1f}" '
            f'rx="10" fill="{theme.PANEL}" stroke="{theme.GRID}"/>'
            f'<rect x="{x + 3:.1f}" y="{y + 3:.1f}" width="4" height="{tile_h - 10:.1f}" rx="2" fill="{colour}"/>'
            f'<text x="{x + 18:.1f}" y="{y + 36:.1f}" font-family="{theme.FONT}" font-size="21" '
            f'font-weight="700" fill="{theme.INK}">{esc(value)}</text>'
            f'<text x="{x + 18:.1f}" y="{y + 54:.1f}" font-family="{theme.FONT}" font-size="11" '
            f'fill="{theme.MUTED}">{esc(_clip(label, int(tile_w / 6)))}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def severity_bar(counts: Dict[str, int], *, width: float = 520, title: str = "") -> str:
    order = ["critical", "high", "medium", "low", "info"]
    items = [(s.title(), counts.get(s, 0)) for s in order if counts.get(s)]
    colours = {s.title(): theme.SEVERITY[s] for s in order}
    return stacked_bar(items, title=title, width=width, colours=colours)


def _open(width: float, height: float, title: str) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'width="100%" height="{height:.0f}" role="img" aria-label="{esc(title or "chart")}" '
        f'preserveAspectRatio="xMinYMin meet" font-family="{theme.FONT}">'
    ]
    if title:
        parts.append(
            f'<text x="0" y="14" font-family="{theme.FONT}" font-size="12.5" font-weight="700" '
            f'fill="{theme.INK}">{esc(title)}</text>'
        )
    return "".join(parts)


def _empty(width: float, height: float, message: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
            f'width="100%" height="{height:.0f}"><text x="0" y="20" font-family="{theme.FONT}" '
            f'font-size="12" fill="{theme.FAINT}">{esc(message)}</text></svg>')


def _clip(text: str, limit: int) -> str:
    text = str(text)
    limit = max(6, limit)
    return text if len(text) <= limit else text[: limit - 1] + "…"
