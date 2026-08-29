"""Minimal vector PDF writer.

Because the layout engine already knows where every box and line goes, the PDF
can be drawn as real vectors — crisp at any zoom, selectable text, no rasteriser
and no third-party dependency.
"""

from __future__ import annotations

import zlib
from typing import List, Optional, Sequence, Tuple

A4_PORTRAIT = (595.28, 841.89)
A4_LANDSCAPE = (841.89, 595.28)

HELVETICA = "F1"
HELVETICA_BOLD = "F2"
COURIER = "F3"

# AFM advance widths (units/1000) for ASCII 32..126.
_HELV = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
]
_HELV_BOLD = [
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
    975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
    333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
]


def text_width(text: str, size: float, bold: bool = False, mono: bool = False) -> float:
    if mono:
        return len(text) * size * 0.6
    table = _HELV_BOLD if bold else _HELV
    total = 0
    for char in text:
        code = ord(char)
        total += table[code - 32] if 32 <= code <= 126 else 556
    return total * size / 1000.0


def wrap_text(text: str, width: float, size: float, bold: bool = False,
              mono: bool = False) -> List[str]:
    words = str(text).split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if text_width(candidate, size, bold, mono) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def escape_pdf(text: str) -> str:
    out = []
    for char in str(text):
        code = ord(char)
        if char in "()\\":
            out.append("\\" + char)
        elif 32 <= code <= 126:
            out.append(char)
        elif code in (9, 10):
            out.append(" ")
        else:
            replacement = {0x2018: "'", 0x2019: "'", 0x201c: '"', 0x201d: '"', 0x2013: "-",
                           0x2014: "-", 0x2026: "...", 0x00b7: "-", 0x2192: "->", 0x00a0: " "}
            out.append(replacement.get(code, "?"))
    return "".join(out)


class Page:
    def __init__(self, width: float, height: float) -> None:
        self.width = width
        self.height = height
        self.ops: List[str] = []

    # ------------------------------------------------------------ helpers
    def _colour(self, colour: str, stroke: bool) -> str:
        r, g, b = hex_to_rgb(colour)
        op = "RG" if stroke else "rg"
        return f"{r:.3f} {g:.3f} {b:.3f} {op}"

    def rect(self, x: float, y: float, w: float, h: float, *, fill: Optional[str] = None,
             stroke: Optional[str] = None, line_width: float = 1.0, radius: float = 0.0) -> None:
        """Coordinates are top-left based; converted to PDF space here."""
        y = self.height - y - h
        if radius > 0:
            self._round_rect(x, y, w, h, radius)
        else:
            self.ops.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re")
        self._paint(fill, stroke, line_width)

    def _round_rect(self, x: float, y: float, w: float, h: float, r: float) -> None:
        r = min(r, w / 2, h / 2)
        k = r * 0.5523
        self.ops.append(f"{x + r:.2f} {y:.2f} m")
        self.ops.append(f"{x + w - r:.2f} {y:.2f} l")
        self.ops.append(f"{x + w - r + k:.2f} {y:.2f} {x + w:.2f} {y + r - k:.2f} {x + w:.2f} {y + r:.2f} c")
        self.ops.append(f"{x + w:.2f} {y + h - r:.2f} l")
        self.ops.append(f"{x + w:.2f} {y + h - r + k:.2f} {x + w - r + k:.2f} {y + h:.2f} "
                        f"{x + w - r:.2f} {y + h:.2f} c")
        self.ops.append(f"{x + r:.2f} {y + h:.2f} l")
        self.ops.append(f"{x + r - k:.2f} {y + h:.2f} {x:.2f} {y + h - r + k:.2f} {x:.2f} {y + h - r:.2f} c")
        self.ops.append(f"{x:.2f} {y + r:.2f} l")
        self.ops.append(f"{x:.2f} {y + r - k:.2f} {x + r - k:.2f} {y:.2f} {x + r:.2f} {y:.2f} c")

    def _paint(self, fill: Optional[str], stroke: Optional[str], line_width: float) -> None:
        if fill:
            self.ops.insert(len(self.ops), "")
            self.ops.append(self._colour(fill, False))
        if stroke:
            self.ops.append(self._colour(stroke, True))
            self.ops.append(f"{line_width:.2f} w")
        if fill and stroke:
            self.ops.append("B")
        elif fill:
            self.ops.append("f")
        elif stroke:
            self.ops.append("S")
        else:
            self.ops.append("n")

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, *, fill: Optional[str] = None,
                stroke: Optional[str] = None, line_width: float = 1.0) -> None:
        cy = self.height - cy
        k = 0.5523
        self.ops.append(f"{cx - rx:.2f} {cy:.2f} m")
        self.ops.append(f"{cx - rx:.2f} {cy + ry * k:.2f} {cx - rx * k:.2f} {cy + ry:.2f} {cx:.2f} {cy + ry:.2f} c")
        self.ops.append(f"{cx + rx * k:.2f} {cy + ry:.2f} {cx + rx:.2f} {cy + ry * k:.2f} {cx + rx:.2f} {cy:.2f} c")
        self.ops.append(f"{cx + rx:.2f} {cy - ry * k:.2f} {cx + rx * k:.2f} {cy - ry:.2f} {cx:.2f} {cy - ry:.2f} c")
        self.ops.append(f"{cx - rx * k:.2f} {cy - ry:.2f} {cx - rx:.2f} {cy - ry * k:.2f} {cx - rx:.2f} {cy:.2f} c")
        self._paint(fill, stroke, line_width)

    def polygon(self, points: Sequence[Tuple[float, float]], *, fill: Optional[str] = None,
                stroke: Optional[str] = None, line_width: float = 1.0, close: bool = True) -> None:
        if not points:
            return
        converted = [(x, self.height - y) for x, y in points]
        self.ops.append(f"{converted[0][0]:.2f} {converted[0][1]:.2f} m")
        for x, y in converted[1:]:
            self.ops.append(f"{x:.2f} {y:.2f} l")
        if close:
            self.ops.append("h")
        self._paint(fill, stroke, line_width)

    def line(self, x1: float, y1: float, x2: float, y2: float, *, colour: str = "#94a3b8",
             width: float = 1.0, dash: Optional[Tuple[float, float]] = None) -> None:
        y1 = self.height - y1
        y2 = self.height - y2
        if dash:
            self.ops.append(f"[{dash[0]} {dash[1]}] 0 d")
        self.ops.append(f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l")
        self.ops.append(self._colour(colour, True))
        self.ops.append(f"{width:.2f} w S")
        if dash:
            self.ops.append("[] 0 d")

    def polyline(self, points: Sequence[Tuple[float, float]], *, colour: str = "#94a3b8",
                 width: float = 1.0, dash: Optional[Tuple[float, float]] = None) -> None:
        if len(points) < 2:
            return
        converted = [(x, self.height - y) for x, y in points]
        if dash:
            self.ops.append(f"[{dash[0]} {dash[1]}] 0 d")
        self.ops.append(f"{converted[0][0]:.2f} {converted[0][1]:.2f} m")
        for x, y in converted[1:]:
            self.ops.append(f"{x:.2f} {y:.2f} l")
        self.ops.append(self._colour(colour, True))
        self.ops.append(f"{width:.2f} w S")
        if dash:
            self.ops.append("[] 0 d")

    def arrow_head(self, x: float, y: float, angle: float, size: float = 5.0,
                   colour: str = "#64748b") -> None:
        import math
        points = [
            (x, y),
            (x - size * math.cos(angle - 0.42), y - size * math.sin(angle - 0.42)),
            (x - size * math.cos(angle + 0.42), y - size * math.sin(angle + 0.42)),
        ]
        self.polygon(points, fill=colour)

    def text(self, x: float, y: float, text: str, *, size: float = 10, bold: bool = False,
             mono: bool = False, colour: str = "#111827", align: str = "left",
             width: float = 0.0) -> None:
        content = escape_pdf(text)
        if align in ("center", "right") and width:
            measured = text_width(text, size, bold, mono)
            if align == "center":
                x = x + (width - measured) / 2
            else:
                x = x + width - measured
        font = COURIER if mono else (HELVETICA_BOLD if bold else HELVETICA)
        self.ops.append("BT")
        self.ops.append(self._colour(colour, False))
        self.ops.append(f"/{font} {size:.2f} Tf")
        self.ops.append(f"1 0 0 1 {x:.2f} {self.height - y:.2f} Tm")
        self.ops.append(f"({content}) Tj")
        self.ops.append("ET")

    def paragraph(self, x: float, y: float, width: float, text: str, *, size: float = 10,
                  leading: float = 1.35, bold: bool = False, mono: bool = False,
                  colour: str = "#111827", max_lines: int = 200) -> float:
        lines = wrap_text(text, width, size, bold, mono)[:max_lines]
        for index, line in enumerate(lines):
            self.text(x, y + index * size * leading, line, size=size, bold=bold, mono=mono,
                      colour=colour)
        return y + len(lines) * size * leading

    def content(self) -> bytes:
        return "\n".join(self.ops).encode("latin-1", "replace")


def hex_to_rgb(colour: str) -> Tuple[float, float, float]:
    colour = (colour or "#000000").lstrip("#")
    if len(colour) == 3:
        colour = "".join(c * 2 for c in colour)
    try:
        return (int(colour[0:2], 16) / 255.0, int(colour[2:4], 16) / 255.0,
                int(colour[4:6], 16) / 255.0)
    except ValueError:
        return (0.0, 0.0, 0.0)


class Document:
    def __init__(self, title: str = "repograph report", author: str = "repograph") -> None:
        self.pages: List[Page] = []
        self.title = title
        self.author = author

    def add_page(self, landscape: bool = False, width: float = 0, height: float = 0) -> Page:
        if width and height:
            page = Page(width, height)
        else:
            size = A4_LANDSCAPE if landscape else A4_PORTRAIT
            page = Page(*size)
        self.pages.append(page)
        return page

    def save(self, path: str, compress: bool = True) -> None:
        objects: List[bytes] = []

        def add_object(data: bytes) -> int:
            objects.append(data)
            return len(objects)  # 1-based object number

        font_ids = {}
        for name, base in ((HELVETICA, "Helvetica"), (HELVETICA_BOLD, "Helvetica-Bold"),
                           (COURIER, "Courier")):
            font_ids[name] = add_object(
                f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} /Encoding /WinAnsiEncoding >>".encode()
            )
        resources = ("<< /Font << " + " ".join(f"/{name} {oid} 0 R" for name, oid in font_ids.items())
                     + " >> >>")

        pages_id = len(objects) + 1 + 2 * len(self.pages)  # reserve
        page_ids: List[int] = []
        for page in self.pages:
            raw = page.content()
            if compress:
                data = zlib.compress(raw)
                stream = (f"<< /Length {len(data)} /Filter /FlateDecode >>\nstream\n").encode() + data \
                         + b"\nendstream"
            else:
                stream = (f"<< /Length {len(raw)} >>\nstream\n").encode() + raw + b"\nendstream"
            content_id = add_object(stream)
            page_id = add_object(
                (f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {page.width:.2f} "
                 f"{page.height:.2f}] /Resources {resources} /Contents {content_id} 0 R >>").encode()
            )
            page_ids.append(page_id)

        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        actual_pages_id = add_object(
            f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
        )
        catalog_id = add_object(f"<< /Type /Catalog /Pages {actual_pages_id} 0 R >>".encode())
        info_id = add_object(
            f"<< /Title ({escape_pdf(self.title)}) /Author ({escape_pdf(self.author)}) "
            f"/Producer (repograph) >>".encode()
        )

        # Page objects referenced ``pages_id`` before it existed; fix the guess.
        if actual_pages_id != pages_id:
            for pid in page_ids:
                objects[pid - 1] = objects[pid - 1].replace(
                    f"/Parent {pages_id} 0 R".encode(), f"/Parent {actual_pages_id} 0 R".encode()
                )

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, data in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode() + data + b"\nendobj\n"
        xref_offset = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode()
        out += b"0000000000 65535 f \n"
        for offset in offsets[1:]:
            out += f"{offset:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R /Info {info_id} 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n").encode()
        with open(path, "wb") as fh:
            fh.write(bytes(out))
