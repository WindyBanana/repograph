"""Terminal output helpers: colour when it helps, plain text when piped."""

from __future__ import annotations

import os
import shutil
import sys
from typing import Sequence

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
COLOURS = {
    "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m", "blue": "\033[34m",
    "magenta": "\033[35m", "cyan": "\033[36m", "grey": "\033[90m", "white": "\033[37m",
    "bright_red": "\033[91m", "bright_green": "\033[92m", "bright_yellow": "\033[93m",
    "bright_blue": "\033[94m",
}
SEVERITY_COLOUR = {
    "critical": "bright_red", "high": "red", "medium": "yellow", "low": "blue", "info": "grey",
}


def supports_colour(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


class Console:
    def __init__(self, quiet: bool = False, colour: bool = None, stream=None) -> None:
        self.stream = stream or sys.stdout
        self.quiet = quiet
        self.colour = supports_colour(self.stream) if colour is None else colour
        self.width = shutil.get_terminal_size((100, 30)).columns

    def paint(self, text: str, colour: str = "", bold: bool = False, dim: bool = False) -> str:
        if not self.colour:
            return text
        prefix = ""
        if colour in COLOURS:
            prefix += COLOURS[colour]
        if bold:
            prefix += BOLD
        if dim:
            prefix += DIM
        return f"{prefix}{text}{RESET}" if prefix else text

    def write(self, text: str = "") -> None:
        if self.quiet:
            return
        self.stream.write(text + "\n")
        self.stream.flush()

    def rule(self, title: str = "") -> None:
        width = min(self.width, 100)
        if title:
            line = f"── {title} " + "─" * max(0, width - len(title) - 4)
        else:
            line = "─" * width
        self.write(self.paint(line, "grey"))

    def header(self, title: str, subtitle: str = "") -> None:
        self.write()
        self.write(self.paint(title, "bright_blue", bold=True))
        if subtitle:
            self.write(self.paint(subtitle, "grey"))

    def item(self, label: str, value: str, colour: str = "") -> None:
        self.write(f"  {self.paint(label.ljust(22), 'grey')} {self.paint(value, colour)}")

    def bullet(self, text: str, colour: str = "") -> None:
        self.write(f"  {self.paint('•', 'grey')} {self.paint(text, colour)}")

    def status(self, text: str) -> None:
        if self.quiet:
            return
        line = f"  {text}"[: max(20, self.width - 2)]
        if self.colour:
            self.stream.write("\r\033[2K" + self.paint(line, "grey"))
        else:
            self.stream.write("\r" + line)
        self.stream.flush()

    def clear_status(self) -> None:
        if self.quiet:
            return
        self.stream.write("\r\033[2K")
        self.stream.flush()

    def table(self, headers: Sequence[str], rows: Sequence[Sequence[str]],
              aligns: Sequence[str] = ()) -> None:
        if not rows:
            self.write(self.paint("  (none)", "grey"))
            return
        columns = len(headers)
        widths = [len(str(h)) for h in headers]
        for row in rows:
            for index in range(columns):
                value = str(row[index]) if index < len(row) else ""
                widths[index] = max(widths[index], len(value))
        budget = min(self.width, 110) - 2 * columns
        while sum(widths) > budget and max(widths) > 8:
            widest = widths.index(max(widths))
            widths[widest] -= 1
        aligns = list(aligns) + ["l"] * (columns - len(aligns))

        def fmt(values: Sequence[str], bold: bool = False, colour: str = "") -> str:
            cells = []
            for index in range(columns):
                value = str(values[index]) if index < len(values) else ""
                if len(value) > widths[index]:
                    value = value[: widths[index] - 1] + "…"
                cells.append(value.rjust(widths[index]) if aligns[index] == "r"
                             else value.ljust(widths[index]))
            return "  " + "  ".join(cells)

        self.write(self.paint(fmt(headers), "grey", bold=True))
        for row in rows:
            self.write(fmt(row))

    def bar(self, label: str, value: float, total: float, width: int = 28,
            colour: str = "blue") -> None:
        ratio = (value / total) if total else 0
        filled = int(round(ratio * width))
        bar = "█" * filled + self.paint("░" * (width - filled), "grey")
        self.write(f"  {label[:20].ljust(20)} {self.paint(bar, colour)} {value:>7,.0f}")
