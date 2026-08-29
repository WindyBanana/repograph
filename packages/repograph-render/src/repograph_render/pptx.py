"""Minimal PPTX writer.

Diagrams are emitted as native DrawingML shapes rather than pictures, so the
deck stays editable: a reviewer can move a box or recolour a lane without
regenerating anything.
"""

from __future__ import annotations

import datetime as _dt
import zipfile
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

EMU_PER_PX = 9525
SLIDE_W = 12192000  # 13.333in (16:9)
SLIDE_H = 6858000

NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def px(value: float) -> int:
    return int(round(value * EMU_PER_PX))


def pt(value: float) -> int:
    return int(round(value * 100))


def _hex(colour: str) -> str:
    colour = (colour or "#000000").lstrip("#")
    return (colour * 2)[:6].upper() if len(colour) == 3 else colour[:6].upper()


@dataclass
class Shape:
    xml: str


class Slide:
    """A slide is just a list of shapes; there are no placeholders to fight."""

    def __init__(self, notes: str = "") -> None:
        self.shapes: List[str] = []
        self.notes = notes
        self._id = 1

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    # ------------------------------------------------------------- shapes
    def text(self, x: float, y: float, w: float, h: float, runs: Sequence[Tuple[str, float, bool, str]],
             *, align: str = "l", anchor: str = "t", spacing: float = 1.0, wrap: bool = True) -> None:
        paragraphs = []
        for text, size, bold, colour in runs:
            lines = str(text).split("\n") or [""]
            for line in lines:
                paragraphs.append(
                    f'<a:p><a:pPr algn="{align}"><a:lnSpc><a:spcPct val="{int(spacing * 100000)}"/></a:lnSpc></a:pPr>'
                    f'<a:r><a:rPr lang="en-US" sz="{pt(size)}" b="{1 if bold else 0}" dirty="0">'
                    f'<a:solidFill><a:srgbClr val="{_hex(colour)}"/></a:solidFill>'
                    f'<a:latin typeface="Calibri"/></a:rPr>'
                    f"<a:t>{escape(str(line))}</a:t></a:r></a:p>"
                )
        body = "".join(paragraphs) or "<a:p/>"
        shape_id = self._next_id()
        self.shapes.append(f"""<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="Text {shape_id}"/>
<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
<p:spPr><a:xfrm><a:off x="{px(x)}" y="{px(y)}"/><a:ext cx="{px(w)}" cy="{px(h)}"/></a:xfrm>
<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>
<p:txBody><a:bodyPr wrap="{'square' if wrap else 'none'}" anchor="{anchor}" lIns="0" tIns="0" rIns="0" bIns="0">
<a:normAutofit/></a:bodyPr><a:lstStyle/>{body}</p:txBody></p:sp>""")

    def box(self, x: float, y: float, w: float, h: float, *, fill: str = "#ffffff",
            line: str = "#94a3b8", line_width: float = 1.25, radius: bool = True,
            text: str = "", text_size: float = 11, text_colour: str = "#0f172a",
            bold: bool = True, subtitle: str = "", shape: str = "roundRect",
            dash: bool = False, fill_alpha: Optional[int] = None) -> None:
        shape_id = self._next_id()
        runs = []
        if text:
            runs.append(f'<a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="en-US" sz="{pt(text_size)}" '
                        f'b="{1 if bold else 0}"><a:solidFill><a:srgbClr val="{_hex(text_colour)}"/>'
                        f'</a:solidFill><a:latin typeface="Calibri"/></a:rPr>'
                        f"<a:t>{escape(text)}</a:t></a:r></a:p>")
        if subtitle:
            runs.append(f'<a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="en-US" sz="{pt(max(8, text_size - 2))}" '
                        f'b="0"><a:solidFill><a:srgbClr val="64748B"/></a:solidFill>'
                        f'<a:latin typeface="Calibri"/></a:rPr><a:t>{escape(subtitle)}</a:t></a:r></a:p>')
        body = "".join(runs) or "<a:p/>"
        alpha = f'<a:alpha val="{fill_alpha}"/>' if fill_alpha is not None else ""
        dash_xml = '<a:prstDash val="dash"/>' if dash else ""
        geom = f'<a:prstGeom prst="{shape}"><a:avLst/></a:prstGeom>'
        self.shapes.append(f"""<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="Box {shape_id}"/>
<p:cNvSpPr/><p:nvPr/></p:nvSpPr>
<p:spPr><a:xfrm><a:off x="{px(x)}" y="{px(y)}"/><a:ext cx="{px(max(w, 1))}" cy="{px(max(h, 1))}"/></a:xfrm>
{geom}<a:solidFill><a:srgbClr val="{_hex(fill)}">{alpha}</a:srgbClr></a:solidFill>
<a:ln w="{int(line_width * 12700)}"><a:solidFill><a:srgbClr val="{_hex(line)}"/></a:solidFill>{dash_xml}</a:ln>
</p:spPr>
<p:txBody><a:bodyPr anchor="ctr" wrap="square" lIns="45720" tIns="18000" rIns="45720" bIns="18000">
<a:normAutofit/></a:bodyPr><a:lstStyle/>{body}</p:txBody></p:sp>""")

    def line(self, x1: float, y1: float, x2: float, y2: float, *, colour: str = "#94a3b8",
             width: float = 1.25, arrow: bool = True, dash: bool = False) -> None:
        shape_id = self._next_id()
        x, y = min(x1, x2), min(y1, y2)
        cx, cy = abs(x2 - x1), abs(y2 - y1)
        flip_h = ' flipH="1"' if x2 < x1 else ""
        flip_v = ' flipV="1"' if y2 < y1 else ""
        head = '<a:tailEnd type="triangle" w="med" len="med"/>' if arrow else ""
        dash_xml = '<a:prstDash val="dash"/>' if dash else ""
        self.shapes.append(f"""<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{shape_id}" name="Line {shape_id}"/>
<p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>
<p:spPr><a:xfrm{flip_h}{flip_v}><a:off x="{px(x)}" y="{px(y)}"/>
<a:ext cx="{px(max(cx, 1))}" cy="{px(max(cy, 1))}"/></a:xfrm>
<a:prstGeom prst="straightConnector1"><a:avLst/></a:prstGeom>
<a:ln w="{int(width * 12700)}"><a:solidFill><a:srgbClr val="{_hex(colour)}"/></a:solidFill>
{dash_xml}{head}</a:ln></p:spPr></p:cxnSp>""")

    def table(self, x: float, y: float, w: float, headers: Sequence[str],
              rows: Sequence[Sequence[str]], *, col_widths: Optional[Sequence[float]] = None,
              row_height: float = 22, font_size: float = 10,
              header_fill: str = "#1e293b", zebra: str = "#f8fafc") -> None:
        shape_id = self._next_id()
        columns = len(headers)
        widths = list(col_widths or [w / columns] * columns)
        total = sum(widths) or w
        widths = [width * w / total for width in widths]
        grid = "".join(f'<a:gridCol w="{px(width)}"/>' for width in widths)

        def cell(text: str, bold: bool, colour: str, fill: Optional[str]) -> str:
            fill_xml = (f'<a:solidFill><a:srgbClr val="{_hex(fill)}"/></a:solidFill>' if fill
                        else "<a:noFill/>")
            return (f'<a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:pPr algn="l"/><a:r>'
                    f'<a:rPr lang="en-US" sz="{pt(font_size)}" b="{1 if bold else 0}">'
                    f'<a:solidFill><a:srgbClr val="{_hex(colour)}"/></a:solidFill>'
                    f'<a:latin typeface="Calibri"/></a:rPr><a:t>{escape(str(text)[:120])}</a:t>'
                    f'</a:r></a:p></a:txBody><a:tcPr marL="45720" marR="45720" marT="18000" '
                    f'marB="18000" anchor="ctr">{fill_xml}</a:tcPr></a:tc>')

        table_rows = [f'<a:tr h="{px(row_height + 4)}">'
                      + "".join(cell(h, True, "#ffffff", header_fill) for h in headers) + "</a:tr>"]
        for index, row in enumerate(rows):
            cells = "".join(
                cell(row[i] if i < len(row) else "", False, "#0f172a",
                     zebra if index % 2 else "#ffffff")
                for i in range(columns)
            )
            table_rows.append(f'<a:tr h="{px(row_height)}">{cells}</a:tr>')
        height = row_height * (len(rows) + 1) + 6
        self.shapes.append(f"""<p:graphicFrame><p:nvGraphicFramePr>
<p:cNvPr id="{shape_id}" name="Table {shape_id}"/><p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/>
</p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr>
<p:xfrm><a:off x="{px(x)}" y="{px(y)}"/><a:ext cx="{px(w)}" cy="{px(height)}"/></p:xfrm>
<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">
<a:tbl><a:tblPr firstRow="1" bandRow="1"/><a:tblGrid>{grid}</a:tblGrid>
{''.join(table_rows)}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>""")

    def bullets(self, x: float, y: float, w: float, h: float, items: Sequence[str],
                *, size: float = 14, colour: str = "#0f172a") -> None:
        paragraphs = "".join(
            f'<a:p><a:pPr marL="228600" indent="-228600"><a:buChar char="•"/></a:pPr>'
            f'<a:r><a:rPr lang="en-US" sz="{pt(size)}"><a:solidFill><a:srgbClr val="{_hex(colour)}"/>'
            f'</a:solidFill><a:latin typeface="Calibri"/></a:rPr>'
            f"<a:t>{escape(str(item))}</a:t></a:r></a:p>"
            for item in items
        ) or "<a:p/>"
        shape_id = self._next_id()
        self.shapes.append(f"""<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="Bullets {shape_id}"/>
<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
<p:spPr><a:xfrm><a:off x="{px(x)}" y="{px(y)}"/><a:ext cx="{px(w)}" cy="{px(h)}"/></a:xfrm>
<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>
<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0"><a:normAutofit/></a:bodyPr>
<a:lstStyle/>{paragraphs}</p:txBody></p:sp>""")

    def to_xml(self) -> str:
        return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<p:sld xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}">'
                f'<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
                f"</p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"0\" cy=\"0\"/>"
                f'<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                f'{"".join(self.shapes)}</p:spTree></p:cSld>'
                f"<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>")


_THEME = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="{NS_A}" name="repograph">
<a:themeElements>
<a:clrScheme name="repograph"><a:dk1><a:srgbClr val="0F172A"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
<a:dk2><a:srgbClr val="1E293B"/></a:dk2><a:lt2><a:srgbClr val="F8FAFC"/></a:lt2>
<a:accent1><a:srgbClr val="2563EB"/></a:accent1><a:accent2><a:srgbClr val="EA580C"/></a:accent2>
<a:accent3><a:srgbClr val="0891B2"/></a:accent3><a:accent4><a:srgbClr val="DB2777"/></a:accent4>
<a:accent5><a:srgbClr val="7C3AED"/></a:accent5><a:accent6><a:srgbClr val="16A34A"/></a:accent6>
<a:hlink><a:srgbClr val="2563EB"/></a:hlink><a:folHlink><a:srgbClr val="7C3AED"/></a:folHlink></a:clrScheme>
<a:fontScheme name="repograph"><a:majorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>
<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>
<a:fmtScheme name="repograph">
<a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>
<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
<a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
<a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>
<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle>
<a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>
<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>
</a:fmtScheme></a:themeElements></a:theme>'''

_SLIDE_LAYOUT = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}" type="blank" preserve="1">
<p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/>
</a:xfrm></p:grpSpPr></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'''

_SLIDE_MASTER = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}">
<p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>
<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/>
</a:xfrm></p:grpSpPr></p:spTree></p:cSld>
<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3"
 accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
</p:sldMaster>'''


def write(path: str, slides: Sequence[Slide], title: str = "repograph") -> None:
    slides = list(slides) or [Slide()]
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    types = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
             '<Default Extension="xml" ContentType="application/xml"/>',
             '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>',
             '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>',
             '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>',
             '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>',
             '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>']
    for index in range(len(slides)):
        types.append(f'<Override PartName="/ppt/slides/slide{index + 1}.xml" '
                     f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>')
    types.append("</Types>")

    slide_ids = "".join(f'<p:sldId id="{256 + i}" r:id="rId{i + 2}"/>' for i in range(len(slides)))
    presentation = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    f'<p:presentation xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}">'
                    f'<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
                    f"<p:sldIdLst>{slide_ids}</p:sldIdLst>"
                    f'<p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}"/>'
                    f'<p:notesSz cx="{SLIDE_H}" cy="{SLIDE_W}"/></p:presentation>')

    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>']
    for index in range(len(slides)):
        rels.append(f'<Relationship Id="rId{index + 2}" '
                    f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
                    f'Target="slides/slide{index + 1}.xml"/>')
    rels.append(f'<Relationship Id="rId{len(slides) + 2}" '
                f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" '
                f'Target="theme/theme1.xml"/>')
    rels.append("</Relationships>")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "".join(types))
        zf.writestr("_rels/.rels",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
                    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                    "</Relationships>")
        zf.writestr("docProps/core.xml",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                    f"<dc:title>{escape(title)}</dc:title><dc:creator>repograph</dc:creator>"
                    f"<cp:lastModifiedBy>repograph</cp:lastModifiedBy>"
                    f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
                    f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
                    "</cp:coreProperties>")
        zf.writestr("ppt/presentation.xml", presentation)
        zf.writestr("ppt/_rels/presentation.xml.rels", "".join(rels))
        zf.writestr("ppt/theme/theme1.xml", _THEME)
        zf.writestr("ppt/slideMasters/slideMaster1.xml", _SLIDE_MASTER)
        zf.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>'
                    "</Relationships>")
        zf.writestr("ppt/slideLayouts/slideLayout1.xml", _SLIDE_LAYOUT)
        zf.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
                    "</Relationships>")
        for index, slide in enumerate(slides):
            zf.writestr(f"ppt/slides/slide{index + 1}.xml", slide.to_xml())
            zf.writestr(f"ppt/slides/_rels/slide{index + 1}.xml.rels",
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
                        "</Relationships>")
