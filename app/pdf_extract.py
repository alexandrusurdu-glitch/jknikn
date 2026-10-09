"""Extragerea segmentelor de text dintr-un PDF, cu informații de aspect.

Un *segment* este unitatea de traducere: un paragraf, un titlu sau o celulă de tabel.
Pornim de la blocurile MuPDF, dar:
  - despărțim o linie în "bucăți" acolo unde există un spațiu orizontal mare sau o linie
    verticală de tabel (altfel celulele unui rând ar fi tratate ca un singur text);
  - unim liniile consecutive ale unui paragraf într-un singur segment (pentru context);
  - păstrăm elementele de listă (•, -, 1.) ca segmente separate.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional

import pymupdf

_FLAGS = pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP
_BULLET_RE = re.compile(r"^(?:[•▪●○►✓✔→–—\-–\*▪■●○►✓→]|\(?\d{1,2}[.)]|\(?[a-zA-Z][.)])\s")


@dataclass
class Segment:
    """Un bloc de text din PDF - unitatea de traducere."""

    id: int
    page: int                                  # index pagină (0-based)
    bbox: tuple[float, float, float, float]    # (x0, y0, x1, y1) în puncte PDF
    text: str                                  # textul sursă, cu liniile unite
    font_size: float
    bold: bool
    italic: bool
    color: int                                 # culoare sRGB ca întreg (0xRRGGBB)
    align: str                                 # left | center | right
    rotate: int                                # 0 | 90 | 180 | 270
    line_count: int
    line_height: float                         # distanța dintre linii (pt), 0 dacă o singură linie
    translation: str = ""
    skipped: bool = False                      # nu are text de tradus (doar coduri/numere)
    from_tm: bool = False                      # provenit din memoria de traducere
    warnings: list[str] = field(default_factory=list)
    scale: float = 1.0                         # factorul de micșorare aplicat la reinserare

    @property
    def rect(self) -> pymupdf.Rect:
        return pymupdf.Rect(*self.bbox)

    @property
    def color_hex(self) -> str:
        return f"#{self.color & 0xFFFFFF:06x}"


@dataclass
class PageInfo:
    index: int
    width: float
    height: float
    segments: list[Segment]
    obstacles: list[tuple[float, float, float, float]]   # dreptunghiuri de evitat la extindere
    is_scanned: bool = False


# --------------------------------------------------------------------------- structuri interne
@dataclass
class _Chunk:
    text: str
    rect: pymupdf.Rect
    size: float
    font: str
    flags: int
    color: int
    rotate: int
    line: int        # indexul liniei în bloc


@dataclass
class _Group:
    chunks: list[_Chunk]
    single_lines: bool      # format doar din linii cu o singură bucată (paragraf)

    @property
    def rect(self) -> pymupdf.Rect:
        r = pymupdf.Rect(self.chunks[0].rect)
        for c in self.chunks[1:]:
            r |= c.rect
        return r

    @property
    def last_line(self) -> int:
        return self.chunks[-1].line

    @property
    def text(self) -> str:
        return self.chunks[-1].text


_WS_RE = re.compile(r"[ \t ]+")


def _join_lines(lines: list[str]) -> str:
    """Unește liniile într-un singur text; tratează despărțirea în silabe la capăt de rând."""
    out = ""
    for raw in lines:
        line = _WS_RE.sub(" ", raw).strip()
        if not line:
            continue
        if not out:
            out = line
            continue
        prev_word = out.rsplit(" ", 1)[-1]
        if out.endswith(("-", "­")) and line[:1].islower() and len(prev_word) > 2 \
                and not re.search(r"\d", prev_word):
            out = out[:-1] + line         # "oper-" + "ation" -> "operation"
        else:
            out = out + " " + line
    return out.strip()


def _dominant(values: Iterable, weights: Iterable[int]):
    c: Counter = Counter()
    for v, w in zip(values, weights):
        c[v] += max(1, w)
    return c.most_common(1)[0][0] if c else None


def _alignment(block_rect: pymupdf.Rect, line_rects: list[pymupdf.Rect]) -> str:
    if len(line_rects) < 2:
        return "left"
    width = block_rect.width or 1.0
    tol = max(1.5, 0.04 * width)
    lefts = [abs(r.x0 - block_rect.x0) for r in line_rects]
    rights = [abs(block_rect.x1 - r.x1) for r in line_rects]
    centers = [abs((r.x0 + r.x1) / 2 - (block_rect.x0 + block_rect.x1) / 2) for r in line_rects]
    if all(l <= tol for l in lefts):
        return "left"
    if all(r <= tol for r in rights):
        return "right"
    if all(c <= tol for c in centers):
        return "center"
    return "left"


def _rotation(direction: tuple[float, float]) -> int:
    dx, dy = direction
    if abs(dx) >= abs(dy):
        return 0 if dx >= 0 else 180
    # Coordonatele PDF au axa y în jos: (0, -1) = textul urcă = rotit 90°
    return 90 if dy < 0 else 270


class _Rules:
    """Liniile de tabel (din desene) folosite ca separatori între celule."""

    def __init__(self, page: pymupdf.Page):
        self.vertical: list[pymupdf.Rect] = []
        self.horizontal: list[pymupdf.Rect] = []
        try:
            for d in page.get_drawings():
                r = d.get("rect")
                if r is None or r.is_empty and r.width == 0 and r.height == 0:
                    continue
                if r.width <= 2.5 and r.height >= 6:
                    self.vertical.append(r)
                elif r.height <= 2.5 and r.width >= 6:
                    self.horizontal.append(r)
        except Exception:  # noqa: BLE001 - desenele nu sunt esențiale
            pass

    def vertical_between(self, a: pymupdf.Rect, b: pymupdf.Rect) -> bool:
        lo, hi = min(a.x1, b.x0), max(a.x1, b.x0)
        y0, y1 = max(a.y0, b.y0), min(a.y1, b.y1)
        for r in self.vertical:
            if lo - 0.5 <= r.x0 <= hi + 0.5 and r.y0 <= y1 and r.y1 >= y0:
                return True
        return False

    def horizontal_between(self, upper: pymupdf.Rect, lower: pymupdf.Rect) -> bool:
        lo, hi = upper.y1 - 1.0, lower.y0 + 1.0
        if hi <= lo:
            return False
        x0, x1 = max(upper.x0, lower.x0), min(upper.x1, lower.x1)
        for r in self.horizontal:
            if lo <= r.y0 <= hi and r.x0 <= x1 and r.x1 >= x0:
                return True
        return False

    def rects(self) -> list[tuple[float, float, float, float]]:
        return [(r.x0, r.y0, r.x1, r.y1) for r in self.vertical + self.horizontal]


def _line_chunks(line: dict, line_idx: int, rules: _Rules) -> list[_Chunk]:
    """Împarte o linie (din rawdict) în bucăți separate de spații mari sau de linii verticale."""
    rotate = _rotation(tuple(line.get("dir", (1, 0))))
    chars: list[tuple[str, pymupdf.Rect, tuple]] = []
    for span in line.get("spans", []):
        style = (round(span.get("size", 9.0), 1), span.get("font", ""), span.get("flags", 0),
                 span.get("color", 0))
        for ch in span.get("chars", []):
            chars.append((ch.get("c", ""), pymupdf.Rect(ch["bbox"]), style))
    if not chars:
        return []

    groups: list[list[tuple[str, pymupdf.Rect, tuple]]] = []
    cur: list[tuple[str, pymupdf.Rect, tuple]] = []
    last_visible: Optional[pymupdf.Rect] = None
    for c, r, st in chars:
        if c.isspace():
            if cur:
                cur.append((c, r, st))
            continue
        if last_visible is not None and rotate == 0:
            gap = r.x0 - last_visible.x1
            threshold = max(2.2 * st[0], 8.0)
            if gap > threshold or (gap > 1.0 and rules.vertical_between(last_visible, r)):
                groups.append(cur)
                cur = []
        cur.append((c, r, st))
        last_visible = r
    if cur:
        groups.append(cur)

    out: list[_Chunk] = []
    for g in groups:
        text = "".join(c for c, _, _ in g).strip()
        if not text:
            continue
        visible = [r for c, r, _ in g if not c.isspace()]
        rect = pymupdf.Rect(visible[0])
        for r in visible[1:]:
            rect |= r
        weights = [1 for c, _, _ in g if not c.isspace()]
        styles = [st for c, _, st in g if not c.isspace()]
        size = _dominant([s[0] for s in styles], weights) or 9.0
        font = _dominant([s[1] for s in styles], weights) or ""
        flags = _dominant([s[2] for s in styles], weights) or 0
        color = _dominant([s[3] for s in styles], weights) or 0
        out.append(_Chunk(text=text, rect=rect, size=float(size), font=font, flags=int(flags),
                          color=int(color), rotate=rotate, line=line_idx))
    return out


def _can_continue(prev: _Chunk, cur: _Chunk) -> bool:
    """Bucata curentă pare continuarea celei anterioare (celulă de tabel cu text pe mai multe linii)."""
    p, c = prev.text.rstrip(), cur.text.lstrip()
    if not p or not c:
        return False
    if p[-1] in ".:;!?":
        return False
    if re.search(r"\d", p[-8:]):
        return False
    return c[0].islower() or c[0] in "(,;/&"


def _group_block(lines: list[dict], rules: _Rules) -> list[_Group]:
    groups: list[_Group] = []
    for li, line in enumerate(lines):
        chunks = _line_chunks(line, li, rules)
        if not chunks:
            continue
        single = len(chunks) == 1
        for ch in chunks:
            target: Optional[_Group] = None
            if not _BULLET_RE.match(ch.text + " "):
                for g in reversed(groups):
                    if g.last_line != li - 1 or g.chunks[-1].rotate != ch.rotate:
                        continue
                    last = g.chunks[-1]
                    if ch.rotate == 0:
                        ov = min(last.rect.x1, ch.rect.x1) - max(last.rect.x0, ch.rect.x0)
                        if ov < 0.5 * min(last.rect.width, ch.rect.width):
                            continue
                        vgap = ch.rect.y0 - last.rect.y1
                        if vgap > 1.2 * max(ch.size, last.size):
                            continue
                        if rules.horizontal_between(last.rect, ch.rect):
                            continue
                    if single and g.single_lines:
                        target = g
                        break
                    if _can_continue(last, ch):
                        target = g
                        break
            if target is None:
                groups.append(_Group(chunks=[ch], single_lines=single))
            else:
                target.chunks.append(ch)
                target.single_lines = target.single_lines and single
    return groups


# --------------------------------------------------------------------------- API
def extract_pages(doc: pymupdf.Document, start_id: int = 0) -> list[PageInfo]:
    """Extrage segmentele și informațiile de pagină din întregul document."""
    pages: list[PageInfo] = []
    next_id = start_id
    for pno, page in enumerate(doc):
        rules = _Rules(page)
        data = page.get_text("rawdict", flags=_FLAGS)
        segments: list[Segment] = []
        obstacles: list[tuple[float, float, float, float]] = list(rules.rects())
        has_text = False
        for block in data.get("blocks", []):
            if block.get("type") == 1:          # imagine
                obstacles.append(tuple(round(v, 2) for v in block["bbox"]))
                continue
            for g in _group_block(block.get("lines", []), rules):
                # textul grupului: bucățile de pe aceeași linie se unesc cu spațiu, liniile se unesc
                per_line: dict[int, list[str]] = {}
                for c in g.chunks:
                    per_line.setdefault(c.line, []).append(c.text)
                text = _join_lines([" ".join(v) for _, v in sorted(per_line.items())])
                if not text:
                    continue
                has_text = True
                rect = g.rect
                bbox = (round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2))
                obstacles.append(bbox)
                w = [len(c.text) for c in g.chunks]
                fsize = _dominant([c.size for c in g.chunks], w) or 9.0
                font = _dominant([c.font for c in g.chunks], w) or ""
                flag = _dominant([c.flags for c in g.chunks], w) or 0
                bold = bool(flag & 16) or bool(re.search(r"bold|black|heavy|semibold", font, re.I))
                italic = bool(flag & 2) or bool(re.search(r"italic|oblique", font, re.I))
                color = _dominant([c.color for c in g.chunks], w) or 0
                rotate = g.chunks[0].rotate
                line_rects = []
                for li in sorted(per_line):
                    lr = None
                    for c in g.chunks:
                        if c.line == li:
                            lr = pymupdf.Rect(c.rect) if lr is None else lr | c.rect
                    if lr is not None:
                        line_rects.append(lr)
                align = _alignment(rect, line_rects) if rotate == 0 else "left"
                line_height = 0.0
                if len(line_rects) > 1 and rotate == 0:
                    ys = sorted(r.y0 for r in line_rects)
                    gaps = [b - a for a, b in zip(ys, ys[1:]) if b - a > 0.5]
                    if gaps:
                        line_height = sum(gaps) / len(gaps)
                segments.append(Segment(
                    id=next_id, page=pno, bbox=bbox, text=text, font_size=float(fsize), bold=bold,
                    italic=italic, color=int(color), align=align, rotate=rotate,
                    line_count=len(line_rects), line_height=round(line_height, 2),
                ))
                next_id += 1
        is_scanned = (not has_text) and bool(page.get_images(full=False))
        pages.append(PageInfo(index=pno, width=page.rect.width, height=page.rect.height,
                              segments=segments, obstacles=obstacles, is_scanned=is_scanned))
    return pages
