"""Reconstrucția PDF-ului: șterge textul original și inserează traducerea în aceleași casete."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Callable, Optional

import pymupdf

from .config import resource_path
from .pdf_extract import PageInfo, Segment

FONT_FILES = {
    (False, False): "DejaVuSans.ttf",
    (True, False): "DejaVuSans-Bold.ttf",
    (False, True): "DejaVuSans-Oblique.ttf",
    (True, True): "DejaVuSans-BoldOblique.ttf",
}

_CSS_FONTS = """
@font-face { font-family: tr; src: url(DejaVuSans.ttf); }
@font-face { font-family: tr; font-weight: bold; src: url(DejaVuSans-Bold.ttf); }
@font-face { font-family: tr; font-style: italic; src: url(DejaVuSans-Oblique.ttf); }
@font-face { font-family: tr; font-weight: bold; font-style: italic; src: url(DejaVuSans-BoldOblique.ttf); }
"""


def fonts_dir() -> Path:
    return resource_path("fonts")


def _css_for(seg: Segment) -> str:
    lh = ""
    if seg.line_height > 0 and seg.font_size > 0:
        ratio = seg.line_height / seg.font_size
        if 0.9 <= ratio <= 2.0:
            lh = f"line-height: {ratio:.3f};"
    return (
        _CSS_FONTS
        + f"body {{ font-family: tr; font-size: {seg.font_size:.2f}pt; color: {seg.color_hex};"
        f" margin: 0; padding: 0; text-align: {seg.align};"
        f" font-weight: {'bold' if seg.bold else 'normal'};"
        f" font-style: {'italic' if seg.italic else 'normal'}; {lh} }}"
        " p { margin: 0; padding: 0; }"
    )


def _expand_rect(seg: Segment, page: PageInfo, max_w_factor: float = 1.6,
                 max_h_factor: float = 1.5, gap: float = 1.5) -> pymupdf.Rect:
    """Extinde caseta spre dreapta și în jos cât timp nu lovește alte blocuri/linii de tabel."""
    r = pymupdf.Rect(seg.bbox)
    if seg.rotate != 0:
        return r
    own = seg.bbox
    limit_x = min(page.width - 6, r.x0 + r.width * max_w_factor)
    limit_y = min(page.height - 6, r.y0 + r.height * max_h_factor)
    for ob in page.obstacles:
        if ob == own:
            continue
        ox0, oy0, ox1, oy1 = ob
        # obstacol la dreapta, suprapus pe verticală cu caseta
        if ox0 >= r.x1 - 0.5 and oy1 > r.y0 + 0.5 and oy0 < r.y1 - 0.5:
            limit_x = min(limit_x, ox0 - gap)
        # obstacol dedesubt, suprapus pe orizontală cu caseta
        if oy0 >= r.y1 - 0.5 and ox1 > r.x0 + 0.5 and ox0 < r.x1 - 0.5:
            limit_y = min(limit_y, oy0 - gap)
    new_x1 = max(r.x1, limit_x)
    new_y1 = max(r.y1, limit_y)
    if seg.align in ("center", "right"):
        # păstrăm centrul (sau marginea dreaptă): extindem și spre stânga cât permite spațiul
        left_limit = 6.0
        for ob in page.obstacles:
            if ob == own:
                continue
            ox0, oy0, ox1, oy1 = ob
            if ox1 <= r.x0 + 0.5 and oy1 > r.y0 + 0.5 and oy0 < r.y1 - 0.5:
                left_limit = max(left_limit, ox1 + gap)
        avail_left = max(0.0, r.x0 - left_limit)
        if seg.align == "right":
            extra = min(avail_left, r.width * (max_w_factor - 1))
            return pymupdf.Rect(r.x0 - extra, r.y0, r.x1, new_y1)
        extra = min(avail_left, new_x1 - r.x1)
        return pymupdf.Rect(r.x0 - extra, r.y0, r.x1 + extra, new_y1)
    return pymupdf.Rect(r.x0, r.y0, new_x1, new_y1)


def _html_for(seg: Segment) -> str:
    text = html.escape(seg.translation, quote=False)
    return "<p>" + text.replace("\n", "<br>") + "</p>"


def rebuild_document(doc: pymupdf.Document, pages: list[PageInfo], *, expand_boxes: bool = True,
                     min_scale_warn: float = 0.6, progress: Optional[Callable[[int], None]] = None,
                     log: Optional[Callable[[str], None]] = None) -> dict:
    """Aplică traducerile în document (in-place). Returnează statistici."""
    log = log or (lambda m: None)
    archive = pymupdf.Archive(str(fonts_dir()))
    stats = {"replaced": 0, "kept": 0, "shrunk": 0, "errors": 0}
    for pinfo in pages:
        page = doc[pinfo.index]
        todo: list[Segment] = []
        for seg in pinfo.segments:
            if seg.skipped or not seg.translation or seg.translation.strip() == seg.text.strip():
                stats["kept"] += 1
                continue
            todo.append(seg)
        if not todo:
            if progress:
                progress(pinfo.index)
            continue
        # 1) ștergem textul original (fără a umple cu alb: fundalul colorat al celulelor rămâne)
        for seg in todo:
            r = pymupdf.Rect(seg.bbox)
            shrink = min(0.6, r.height * 0.08)
            rr = pymupdf.Rect(r.x0 + shrink, r.y0 + shrink, r.x1 - shrink, r.y1 - shrink)
            if rr.is_empty or not rr.is_valid:
                rr = r
            page.add_redact_annot(rr, fill=False)
        try:
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                                  graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                                  text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        except TypeError:  # versiuni mai vechi de PyMuPDF
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
        # 2) inserăm traducerile
        for seg in todo:
            rect = _expand_rect(seg, pinfo) if expand_boxes else pymupdf.Rect(seg.bbox)
            try:
                spare, scale = page.insert_htmlbox(rect, _html_for(seg), css=_css_for(seg),
                                                   archive=archive, scale_low=0, rotate=seg.rotate)
                seg.scale = float(scale) if scale else 1.0
                if seg.scale < min_scale_warn:
                    seg.warnings.append(f"text micșorat la {seg.scale:.0%} ca să încapă")
                    stats["shrunk"] += 1
                stats["replaced"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                seg.warnings.append(f"nu s-a putut insera textul: {exc}")
                log(f"  ! pagina {pinfo.index + 1}, segment {seg.id}: {exc}")
        if progress:
            progress(pinfo.index)
    return stats


def make_compare_document(original: pymupdf.Document, translated: pymupdf.Document) -> pymupdf.Document:
    """PDF cu paginile alternate: original, traducere, original, traducere ..."""
    out = pymupdf.open()
    for i in range(len(original)):
        out.insert_pdf(original, from_page=i, to_page=i)
        if i < len(translated):
            out.insert_pdf(translated, from_page=i, to_page=i)
    return out
