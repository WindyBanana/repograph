"""Minimal XLSX writer.

A spreadsheet is a zip of XML, so this needs no third-party library: styled
header row, frozen panes, autofilter, column widths, real numbers and a
severity colour scale for the findings sheet.
"""

from __future__ import annotations

import datetime as _dt
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence
from xml.sax.saxutils import escape

# style ids defined in styles.xml below
STYLE_DEFAULT = 0
STYLE_HEADER = 1
STYLE_MONO = 2
STYLE_NUMBER = 3
STYLE_WRAP = 4
STYLE_CRITICAL = 5
STYLE_HIGH = 6
STYLE_MEDIUM = 7
STYLE_LOW = 8
STYLE_INFO = 9
STYLE_TITLE = 10

SEVERITY_STYLE = {
    "critical": STYLE_CRITICAL, "high": STYLE_HIGH, "medium": STYLE_MEDIUM,
    "low": STYLE_LOW, "info": STYLE_INFO,
}

_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass
class Sheet:
    name: str
    headers: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    widths: List[float] = field(default_factory=list)
    styles: Dict[int, int] = field(default_factory=dict)   # row index -> style id
    freeze: bool = True
    autofilter: bool = True
    note: str = ""

    def add(self, row: Sequence[Any], style: Optional[int] = None) -> None:
        if style is not None:
            self.styles[len(self.rows)] = style
        self.rows.append(list(row))


def column_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _clean(value: str) -> str:
    return _ILLEGAL.sub("", str(value))[:32000]


def _cell(ref: str, value: Any, style: int) -> str:
    if value is None or value == "":
        return f'<c r="{ref}" s="{style}"/>'
    if isinstance(value, bool):
        return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t>{"TRUE" if value else "FALSE"}</t></is></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}" s="{style if style else STYLE_NUMBER}"><v>{value}</v></c>'
    text = escape(_clean(value))
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_xml(sheet: Sheet) -> str:
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
    if sheet.widths:
        cols = "".join(
            f'<col min="{i+1}" max="{i+1}" width="{w:.1f}" customWidth="1"/>'
            for i, w in enumerate(sheet.widths)
        )
        parts.append(f"<cols>{cols}</cols>")
    parts.append("<sheetData>")

    row_number = 1
    if sheet.headers:
        cells = "".join(_cell(f"{column_name(i)}{row_number}", h, STYLE_HEADER)
                        for i, h in enumerate(sheet.headers))
        parts.append(f'<row r="{row_number}" ht="20" customHeight="1">{cells}</row>')
        row_number += 1
    for index, row in enumerate(sheet.rows):
        style = sheet.styles.get(index, STYLE_DEFAULT)
        cells = "".join(_cell(f"{column_name(i)}{row_number}", value, style)
                        for i, value in enumerate(row))
        parts.append(f'<row r="{row_number}">{cells}</row>')
        row_number += 1
    parts.append("</sheetData>")
    if sheet.autofilter and sheet.headers and sheet.rows:
        last = f"{column_name(len(sheet.headers) - 1)}{len(sheet.rows) + 1}"
        parts.append(f'<autoFilter ref="A1:{last}"/>')
    parts.append("</worksheet>")

    if sheet.freeze and sheet.headers:
        parts.insert(2, '<sheetViews><sheetView workbookViewId="0">'
                        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                        '</sheetView></sheetViews>')
    return "".join(parts)


_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="5">
  <font><sz val="11"/><name val="Calibri"/></font>
  <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
  <font><sz val="10"/><name val="Consolas"/></font>
  <font><b/><sz val="14"/><name val="Calibri"/></font>
  <font><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
</fonts>
<fills count="8">
  <fill><patternFill patternType="none"/></fill>
  <fill><patternFill patternType="gray125"/></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FF1E293B"/><bgColor indexed="64"/></patternFill></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FF991B1B"/><bgColor indexed="64"/></patternFill></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FFC2410C"/><bgColor indexed="64"/></patternFill></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FFFDE68A"/><bgColor indexed="64"/></patternFill></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FFDBEAFE"/><bgColor indexed="64"/></patternFill></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FFF1F5F9"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
  <border><left/><right/><top/><bottom/><diagonal/></border>
  <border><left/><right/><top/><bottom style="thin"><color rgb="FFE2E8F0"/></bottom><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="11">
  <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"><alignment vertical="top"/></xf>
  <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"><alignment vertical="center"/></xf>
  <xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1"><alignment vertical="top"/></xf>
  <xf numFmtId="1" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"><alignment horizontal="right"/></xf>
  <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"><alignment wrapText="1" vertical="top"/></xf>
  <xf numFmtId="0" fontId="4" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"><alignment vertical="top"/></xf>
  <xf numFmtId="0" fontId="4" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"><alignment vertical="top"/></xf>
  <xf numFmtId="0" fontId="0" fillId="5" borderId="1" xfId="0" applyFill="1" applyBorder="1"><alignment vertical="top"/></xf>
  <xf numFmtId="0" fontId="0" fillId="6" borderId="1" xfId="0" applyFill="1" applyBorder="1"><alignment vertical="top"/></xf>
  <xf numFmtId="0" fontId="0" fillId="7" borderId="1" xfId="0" applyFill="1" applyBorder="1"><alignment vertical="top"/></xf>
  <xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def write(path: str, sheets: Sequence[Sheet], title: str = "repograph") -> None:
    sheets = [s for s in sheets if s.headers or s.rows] or [Sheet(name="Empty", headers=["(no data)"])]
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    content_types = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
                     '<Default Extension="xml" ContentType="application/xml"/>',
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
                     '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
                     '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>']
    for index in range(len(sheets)):
        content_types.append(
            f'<Override PartName="/xl/worksheets/sheet{index + 1}.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    content_types.append("</Types>")

    workbook_sheets = "".join(
        f'<sheet name="{escape(_sheet_name(s.name, index))}" sheetId="{index + 1}" r:id="rId{index + 1}"/>'
        for index, s in enumerate(sheets)
    )
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f"<sheets>{workbook_sheets}</sheets></workbook>")

    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for index in range(len(sheets)):
        rels.append(f'<Relationship Id="rId{index + 1}" '
                    f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                    f'Target="worksheets/sheet{index + 1}.xml"/>')
    rels.append(f'<Relationship Id="rId{len(sheets) + 1}" '
                f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
                f'Target="styles.xml"/>')
    rels.append("</Relationships>")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "".join(content_types))
        zf.writestr("_rels/.rels",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                    "</Relationships>")
        zf.writestr("docProps/core.xml",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                    f"<dc:title>{escape(title)}</dc:title><dc:creator>repograph</dc:creator>"
                    f'<cp:lastModifiedBy>repograph</cp:lastModifiedBy>'
                    f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
                    f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
                    "</cp:coreProperties>")
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", "".join(rels))
        zf.writestr("xl/styles.xml", _STYLES)
        for index, sheet in enumerate(sheets):
            zf.writestr(f"xl/worksheets/sheet{index + 1}.xml", _sheet_xml(sheet))


_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def _sheet_name(name: str, index: int) -> str:
    cleaned = _BAD_SHEET_CHARS.sub("-", str(name)).strip()[:31]
    return cleaned or f"Sheet{index + 1}"
