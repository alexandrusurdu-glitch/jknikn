"""Test de fum al fluxului complet, fără internet: folosește un motor fictiv care emulează o
traducere (dicționar mic + sufixe), păstrând marcajele protejate.

Rulare:  python -m tests.test_pipeline [folder_iesire]
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Consolele Windows (cp1252) nu pot afișa diacriticele: evităm UnicodeEncodeError la print.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

from app import engines as eng  # noqa: E402
from app.config import Settings  # noqa: E402
from app.glossary import Glossary  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402
from tests.make_sample_pdf import make_sample  # noqa: E402

_DICT = {
    "miniature circuit breaker": "întrerupător automat miniatural",
    "miniature circuit breakers": "întrerupătoarele automate miniaturale",
    "circuit breaker": "întrerupător automat",
    "product data sheet": "fișă tehnică a produsului",
    "technical data": "date tehnice",
    "rated current": "curent nominal", "rated voltage": "tensiune nominală",
    "rated frequency": "frecvență nominală", "breaking capacity": "capacitate de rupere",
    "tripping curve": "curbă de declanșare", "number of poles": "număr de poli",
    "degree of protection": "grad de protecție", "operating temperature": "temperatură de funcționare",
    "conductor cross section": "secțiunea conductorului", "tightening torque": "cuplu de strângere",
    "electrical endurance": "anduranță electrică", "weight": "greutate", "standards": "standarde",
    "characteristic": "caracteristică", "value": "valoare", "warning": "AVERTISMENT",
    "accessories": "accesorii", "auxiliary contact": "contact auxiliar", "shunt trip": "declanșator de tensiune",
    "coil voltage": "tensiunea bobinei", "comb busbar": "bară tip pieptene", "order no.": "cod de comandă",
    "modules": "module", "operating cycles": "cicluri de funcționare", "in enclosure": "în carcasă",
    "rigid": "rigid", "flexible": "flexibil", "page": "pagina", "of": "din",
    "subject to technical changes": "sub rezerva modificărilor tehnice",
    "available in": "disponibil în variantele", "and": "și", "versions": "",
    "width in": "lățime în",
}


class MockEngine(eng.TestEngine):
    """Emulează o traducere: dicționar + marcaje păstrate + text ceva mai lung (ca în română)."""

    name = "Mock"
    id = "mock"

    def translate_batch(self, texts):
        out = []
        for t in texts:
            low = t
            for k in sorted(_DICT, key=len, reverse=True):
                low = re.sub(r"(?<!\w)" + re.escape(k) + r"(?!\w)", _DICT[k], low, flags=re.I)
            if low == t and re.search(r"[^\W\d_]{3,}", re.sub(r"⟦\d+⟧", "", t)):
                low = "[RO] " + t          # text netradus de dicționar
            out.append(low)
        return out


def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    sample = make_sample(out_dir / "sample_datasheet.pdf")
    s = Settings(engine="test", out_pdf=True, out_docx=True, out_report=True, out_compare=True, use_tm=False)
    original_make = eng.make_engine
    eng.make_engine = lambda settings, glossary=None, cancel=None, log=None: MockEngine(
        source_lang=settings.source_lang, cancel=cancel, log=log)
    try:
        p = Pipeline(s, Glossary.load(), log=print, progress=lambda f, m: None)
        res = p.run_file(sample, out_dir)
    finally:
        eng.make_engine = original_make
    print("\nIeșiri:", [o.name for o in res["outputs"]])
    print("Avertismente:", res["warnings"])
    for pinfo in res["pages"]:
        for seg in pinfo.segments:
            flag = "!" if seg.warnings else " "
            print(f" {flag} [{seg.id + 1:2d}] {seg.text[:48]!r:52} -> {seg.translation[:52]!r} {seg.warnings}")
    # Verificări minime
    assert (out_dir / "sample_datasheet_RO.pdf").exists()
    assert (out_dir / "sample_datasheet_RO_bilingv.docx").exists()
    assert (out_dir / "sample_datasheet_RO_raport.html").exists()
    import pymupdf
    txt = pymupdf.open(str(out_dir / "sample_datasheet_RO.pdf"))[0].get_text()
    assert "16 A" in txt and "A9" not in txt and "60898-1:2019" in txt, "tokenii protejați trebuie păstrați"
    assert "curent nominal" in txt.lower(), "traducerea trebuie să apară în PDF"
    print("\nOK - testul de fum a trecut.")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="pdftr_"))
    raise SystemExit(main(target))
