"""Fluxul complet de traducere a unui PDF: extragere -> protejare -> traducere -> post-editare ->
verificare -> reconstrucție PDF -> DOCX bilingv + raport."""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Callable, Optional

import pymupdf

from . import engines as eng
from .config import Settings
from .glossary import Glossary
from .langdetect_lite import detect_language
from .outputs import now_str, write_bilingual_docx, write_report_html
from .pdf_extract import Segment, extract_pages
from .pdf_rebuild import make_compare_document, rebuild_document
from .protect import Protected, Protector, has_letters, numbers_match
from .tm_cache import TranslationMemory

LogFn = Callable[[str], None]
ProgressFn = Callable[[float, str], None]


class Pipeline:
    def __init__(self, settings: Settings, glossary: Optional[Glossary] = None,
                 log: Optional[LogFn] = None, progress: Optional[ProgressFn] = None,
                 cancel: Optional[threading.Event] = None):
        self.settings = settings
        self.glossary = glossary or Glossary.load()
        self.log = log or (lambda m: None)
        self.progress = progress or (lambda f, m: None)
        self.cancel = cancel or threading.Event()
        self.tm = TranslationMemory(enabled=settings.use_tm)

    # ------------------------------------------------------------------ utilitare
    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise eng.CancelledError()

    @staticmethod
    def _batches(items: list, max_items: int, max_chars: int):
        batch, size = [], 0
        for it in items:
            n = len(it)
            if batch and (len(batch) >= max_items or size + n > max_chars):
                yield batch
                batch, size = [], 0
            batch.append(it)
            size += n
        if batch:
            yield batch

    # ------------------------------------------------------------------ fluxul principal
    def run_file(self, pdf_path: Path, out_dir: Path) -> dict:
        s = self.settings
        pdf_path, out_dir = Path(pdf_path), Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"Deschid: {pdf_path.name}")
        doc = pymupdf.open(str(pdf_path))
        if doc.needs_pass:
            raise eng.TranslationError("PDF-ul este protejat cu parolă.")
        pages = extract_pages(doc)
        all_segments = [seg for p in pages for seg in p.segments]
        self.log(f"  {len(doc)} pagini, {len(all_segments)} segmente de text")
        scanned = [p.index + 1 for p in pages if p.is_scanned]
        if scanned:
            self.log(f"  ! pagini fără text (scanate), netraduse: {scanned}")

        # Limba sursă
        lang = (s.source_lang or "auto").lower()
        if lang == "auto":
            detected = detect_language(" ".join(seg.text for seg in all_segments[:400]))
            if detected != "auto":
                lang = detected
                self.log(f"  limbă sursă detectată: {lang}")
            else:
                self.log("  limba sursă nu a putut fi detectată; motorul va detecta automat")
        if lang == "ro":
            self.log("  ! documentul pare să fie deja în română")

        # Motor (creat per fișier, ca să primească limba detectată)
        eff = copy.copy(s)
        eff.source_lang = lang
        engine = eng.make_engine(eff, glossary=self.glossary, cancel=self.cancel, log=self.log)
        editor: Optional[eng.ClaudeEngine] = None
        if s.post_edit and engine.id != "claude":
            editor = eng.ClaudeEngine(api_key=s.anthropic_key.strip(), model=s.claude_model,
                                      glossary=self.glossary, source_lang=lang, cancel=self.cancel,
                                      log=self.log, request_delay=float(s.request_delay or 0))
        key_mt = engine.id + (f":{s.claude_model}" if engine.id == "claude" else "")
        key_final = key_mt + (f"+pe:{s.claude_model}" if editor else "")

        protector = Protector(keep_terms=self.glossary.keep_terms(), protect_numbers=s.protect_tokens,
                              decimal_comma=s.decimal_comma)

        try:
            prot_map: dict[int, Protected] = {}
            to_translate: list[Segment] = []
            from_tm = 0
            for seg in all_segments:
                pr = protector.protect(seg.text)
                prot_map[seg.id] = pr
                if not has_letters(seg.text) or not pr.has_translatable_text:
                    seg.skipped = True
                    seg.translation = seg.text
                    continue
                cached = self.tm.get(key_final, pr.text)
                if cached is not None:
                    seg.translation, missing = protector.restore(cached, pr)
                    seg.from_tm = True
                    from_tm += 1
                    if missing:
                        seg.warnings.append("marcaje protejate lipsă în memoria de traducere")
                    continue
                to_translate.append(seg)
            self.log(f"  de tradus: {len(to_translate)} segmente ({from_tm} din memoria de traducere, "
                     f"{sum(1 for x in all_segments if x.skipped)} fără text de tradus)")

            total_units = max(1, len(to_translate) + len(pages))
            done_units = 0

            # ---- traducere automată, pe pagini, cu deduplicare la nivel de fișier
            drafts: dict[str, str] = {}      # text protejat -> traducere brută (cu marcaje)
            for pinfo in pages:
                self._check_cancel()
                page_segs = [x for x in to_translate if x.page == pinfo.index]
                uniq: list[str] = []
                for x in page_segs:
                    pt = prot_map[x.id].text
                    if pt in drafts or pt in uniq:
                        continue
                    cached = self.tm.get(key_mt, pt)
                    if cached is not None:
                        drafts[pt] = cached
                        continue
                    uniq.append(pt)
                for batch in self._batches(uniq, engine.max_items, engine.max_chars):
                    self._check_cancel()
                    out = engine.translate_batch(batch)
                    for src_p, tgt_p in zip(batch, out):
                        drafts[src_p] = tgt_p
                        self.tm.put(key_mt, src_p, tgt_p)
                    done_units += len(batch)
                    self.progress(done_units / total_units,
                                  f"{pdf_path.name}: pagina {pinfo.index + 1}/{len(pages)} - traducere")
                # ---- post-editare contextuală (pe pagină)
                if editor is not None and page_segs:
                    srcs = [prot_map[x.id].text for x in page_segs]
                    srcs_u = list(dict.fromkeys(srcs))
                    for batch in self._batches(srcs_u, editor.max_items, editor.max_chars):
                        self._check_cancel()
                        edited = editor.post_edit(batch, [drafts[t] for t in batch])
                        for src_p, tgt_p in zip(batch, edited):
                            # acceptăm post-editarea doar dacă păstrează toate marcajele
                            if tgt_p.count("⟦") == src_p.count("⟦"):
                                drafts[src_p] = tgt_p
                            else:
                                self.log("  · post-editarea a modificat marcajele; păstrez traducerea brută")
                    self.progress(done_units / total_units,
                                  f"{pdf_path.name}: pagina {pinfo.index + 1}/{len(pages)} - post-editare")

            # ---- restaurare marcaje + verificări
            for seg in to_translate:
                pr = prot_map[seg.id]
                raw = drafts.get(pr.text, "")
                translated, missing = protector.restore(raw, pr)
                if missing or not translated.strip():
                    # Reîncercăm fără protejare (unele motoare strică marcajele); verificăm cifrele.
                    self.log(f"  · marcaje pierdute în segmentul {seg.id + 1}; retraduc fără protejare")
                    try:
                        translated = engine.translate_batch([seg.text])[0]
                    except eng.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        translated = seg.text
                        seg.warnings.append(f"netradus (eroare: {str(exc)[:80]})")
                    seg.warnings.append("marcaje protejate pierdute; segment retradus fără protejare")
                seg.translation = translated.strip() or seg.text
                ok, miss, extra = numbers_match(seg.text, seg.translation)
                if not ok:
                    seg.warnings.append(
                        "numere diferite față de sursă" +
                        (f" (lipsă: {', '.join(miss[:6])})" if miss else "") +
                        (f" (în plus: {', '.join(extra[:6])})" if extra else "")
                    )
                if seg.translation.strip() != seg.text.strip():
                    for e in self.glossary.check(seg.text, seg.translation, lang):
                        seg.warnings.append(f"glosar: '{e.src}' => '{e.ro}' nu apare în traducere")
                if raw and not missing:
                    self.tm.put(key_final, pr.text, raw)

            # Segmentele din memorie primesc și ele verificările
            for seg in all_segments:
                if seg.from_tm:
                    ok, miss, extra = numbers_match(seg.text, seg.translation)
                    if not ok:
                        seg.warnings.append("numere diferite față de sursă")

            # ---- reconstrucție PDF
            results: dict = {"file": str(pdf_path), "outputs": [], "warnings": 0}
            stats = {}
            if s.out_pdf or s.out_compare:
                self.log("  reconstruiesc PDF-ul cu textul tradus")
                stats = rebuild_document(
                    doc, pages, expand_boxes=s.expand_boxes, min_scale_warn=s.min_scale_warn,
                    progress=lambda i: self.progress((done_units + i + 1) / total_units,
                                                     f"{pdf_path.name}: pagina {i + 1}/{len(pages)} - reconstrucție"),
                    log=self.log,
                )
                out_pdf = out_dir / f"{pdf_path.stem}_RO.pdf"
                doc.save(str(out_pdf), garbage=3, deflate=True)
                if s.out_pdf:
                    results["outputs"].append(out_pdf)
                    self.log(f"  salvat: {out_pdf.name}")
                if s.out_compare:
                    orig = pymupdf.open(str(pdf_path))
                    trans = pymupdf.open(str(out_pdf))
                    cmp_doc = make_compare_document(orig, trans)
                    out_cmp = out_dir / f"{pdf_path.stem}_RO_comparativ.pdf"
                    cmp_doc.save(str(out_cmp), garbage=3, deflate=True)
                    cmp_doc.close(); orig.close(); trans.close()
                    results["outputs"].append(out_cmp)
                    self.log(f"  salvat: {out_cmp.name}")
                    if not s.out_pdf:
                        out_pdf.unlink(missing_ok=True)
            doc.close()

            n_warn = sum(1 for x in all_segments if x.warnings)
            meta = {
                "file": pdf_path.name, "engine": engine.name, "post_edit": editor is not None,
                "lang": lang, "date": now_str(), "total": len(all_segments),
                "translated": len(to_translate), "kept": sum(1 for x in all_segments if x.skipped),
                "from_tm": from_tm, "warnings": n_warn, "stats": stats,
            }
            if s.out_docx:
                out_docx = out_dir / f"{pdf_path.stem}_RO_bilingv.docx"
                write_bilingual_docx(pages, out_docx, meta)
                results["outputs"].append(out_docx)
                self.log(f"  salvat: {out_docx.name}")
            if s.out_report:
                out_rep = out_dir / f"{pdf_path.stem}_RO_raport.html"
                write_report_html(pages, out_rep, meta)
                results["outputs"].append(out_rep)
                self.log(f"  salvat: {out_rep.name}")
            results["warnings"] = n_warn
            results["meta"] = meta
            results["pages"] = pages
            self.progress(1.0, f"{pdf_path.name}: gata ({n_warn} avertismente)")
            self.log(f"Gata: {pdf_path.name} - {n_warn} segmente de verificat")
            return results
        finally:
            try:
                engine.close()
            except Exception:  # noqa: BLE001
                pass
            if not doc.is_closed:
                doc.close()

    def close(self) -> None:
        self.tm.close()
