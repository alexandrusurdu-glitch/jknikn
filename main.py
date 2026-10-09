"""Punct de intrare: fără argumente pornește interfața grafică; cu argumente rulează în linie de comandă.

Exemple:
    python main.py                                   -> interfața grafică
    python main.py fisa.pdf                          -> traduce cu setările salvate, lângă fișier
    python main.py *.pdf --out C:\\traduse --engine deepl --post-edit
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path


def _ensure_streams() -> None:
    """În executabilul fără consolă (PyInstaller --windowed) stdout/stderr pot fi None."""
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()


def run_cli(argv: list[str]) -> int:
    from app.config import Settings
    from app.engines import CancelledError, TranslationError
    from app.glossary import Glossary
    from app.pipeline import Pipeline

    parser = argparse.ArgumentParser(prog="PDFTranslatorRO", description="Traduce fișiere PDF în limba română.")
    parser.add_argument("pdf", nargs="+", help="fișiere PDF de tradus")
    parser.add_argument("--out", help="folder de ieșire (implicit: lângă fișierul sursă)")
    parser.add_argument("--engine", choices=["google", "deepl", "claude", "test"], help="motorul de traducere")
    parser.add_argument("--lang", help="limba sursă (auto, en, de, fr, ...)")
    parser.add_argument("--post-edit", action="store_true", help="post-editare contextuală cu Claude")
    parser.add_argument("--no-docx", action="store_true", help="nu genera DOCX bilingv")
    parser.add_argument("--no-report", action="store_true", help="nu genera raportul HTML")
    parser.add_argument("--compare", action="store_true", help="generează și PDF comparativ")
    args = parser.parse_args(argv)

    s = Settings.load()
    if args.engine:
        s.engine = args.engine
    if args.lang:
        s.source_lang = args.lang
    if args.post_edit:
        s.post_edit = True
    s.out_docx = not args.no_docx
    s.out_report = not args.no_report
    s.out_compare = args.compare or s.out_compare

    files: list[Path] = []
    for pattern in args.pdf:
        p = Path(pattern)
        if any(ch in pattern for ch in "*?["):
            files.extend(sorted(p.parent.glob(p.name)))
        else:
            files.append(p)
    if not files:
        print("Niciun fișier PDF găsit.")
        return 2

    pipeline = Pipeline(s, Glossary.load(), log=print)
    code = 0
    try:
        for pdf in files:
            try:
                pipeline.run_file(pdf, Path(args.out) if args.out else pdf.parent)
            except TranslationError as exc:
                print(f"EROARE ({pdf.name}): {exc}")
                code = 1
    except (CancelledError, KeyboardInterrupt):
        print("\nOprit.")
        code = 130
    finally:
        pipeline.close()
    return code


def main() -> None:
    _ensure_streams()
    # PyInstaller: resursele și modulele sunt lângă executabil / în _MEIPASS; sursa: lângă main.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-psn"):
        raise SystemExit(run_cli(sys.argv[1:]))
    from app.gui import run
    run()


if __name__ == "__main__":
    main()
