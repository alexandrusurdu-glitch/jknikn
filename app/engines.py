"""Motoarele de traducere: Google (gratuit), DeepL (API), Claude (API) și motorul de test.

Toate primesc segmente deja "protejate" (cu marcaje ⟦n⟧) și trebuie să le returneze în
aceeași ordine. Claude este folosit și pentru post-editarea contextuală a traducerii automate.
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional, Sequence

TARGET_LANG = "ro"


class TranslationError(Exception):
    """Eroare definitivă a motorului de traducere (după reîncercări)."""


class CancelledError(Exception):
    """Operație anulată de utilizator."""


def _retry(fn: Callable[[], object], attempts: int = 4, base_delay: float = 1.5,
           cancel: Optional[threading.Event] = None, log: Optional[Callable[[str], None]] = None):
    last: Optional[BaseException] = None
    for i in range(attempts):
        if cancel is not None and cancel.is_set():
            raise CancelledError()
        try:
            return fn()
        except CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - reîncercăm orice eroare de rețea/API
            last = exc
            delay = base_delay * (2 ** i)
            # erorile de tip "prea multe cereri" primesc o pauză mai lungă
            if "429" in str(exc) or "Too Many" in str(exc) or "rate" in str(exc).lower():
                delay = max(delay, 8.0 * (i + 1))
            if log:
                log(f"  ! {type(exc).__name__}: {str(exc)[:160]} - reîncerc în {delay:.0f}s")
            if i < attempts - 1:
                waited = 0.0
                while waited < delay:
                    if cancel is not None and cancel.is_set():
                        raise CancelledError()
                    time.sleep(0.25)
                    waited += 0.25
    raise TranslationError(str(last))


# --------------------------------------------------------------------------- bază
class Engine:
    name = "base"
    id = "base"
    # Numărul maxim de caractere trimis într-o singură cerere
    max_chars = 3500
    max_items = 40

    def __init__(self, source_lang: str = "auto", cancel: Optional[threading.Event] = None,
                 log: Optional[Callable[[str], None]] = None, request_delay: float = 0.0):
        self.source_lang = (source_lang or "auto").lower()
        self.cancel = cancel
        self.log = log or (lambda msg: None)
        self.request_delay = request_delay

    def check_cancel(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise CancelledError()

    def translate_batch(self, texts: Sequence[str]) -> list[str]:
        raise NotImplementedError

    def translate(self, text: str) -> str:
        return self.translate_batch([text])[0]

    def _pause(self) -> None:
        if self.request_delay > 0:
            time.sleep(self.request_delay)

    def close(self) -> None:
        pass


# --------------------------------------------------------------------------- test
class TestEngine(Engine):
    """Nu traduce nimic - returnează textul sursă. Util pentru a verifica păstrarea aspectului."""

    name = "Test (fără traducere)"
    id = "test"

    def translate_batch(self, texts: Sequence[str]) -> list[str]:
        self.check_cancel()
        return list(texts)


# --------------------------------------------------------------------------- Google
class GoogleEngine(Engine):
    """Google Translate prin biblioteca deep-translator (gratuit, fără cheie API)."""

    name = "Google Translate (gratuit)"
    id = "google"
    max_chars = 4500
    max_items = 60
    workers = 3

    def __init__(self, **kw):
        super().__init__(**kw)
        from deep_translator import GoogleTranslator  # import leneș: pornire mai rapidă

        src = "auto" if self.source_lang in ("auto", "") else self.source_lang
        if src == "zh":
            src = "zh-CN"  # Google cere varianta de chineză
        try:
            self._tr = GoogleTranslator(source=src, target=TARGET_LANG)
        except Exception:  # noqa: BLE001 - cod de limbă neacceptat: lăsăm detectarea automată
            self._tr = GoogleTranslator(source="auto", target=TARGET_LANG)

    def _one(self, text: str) -> str:
        def call():
            self._pause()
            out = self._tr.translate(text)
            if out is None:
                return text
            return out
        return str(_retry(call, cancel=self.cancel, log=self.log))

    def translate_batch(self, texts: Sequence[str]) -> list[str]:
        self.check_cancel()
        texts = list(texts)
        if not texts:
            return []
        # Încercăm un singur apel cu segmentele separate prin linii noi.
        if len(texts) > 1 and all("\n" not in t for t in texts):
            joined = "\n".join(texts)
            if len(joined) <= self.max_chars:
                try:
                    out = self._one(joined)
                    parts = [p.strip() for p in out.split("\n")]
                    if len(parts) == len(texts):
                        return parts
                    self.log("  · lotul Google nu a păstrat separatorii; traduc segmentele individual")
                except TranslationError as exc:
                    self.log(f"  · lotul Google a eșuat ({exc}); traduc segmentele individual")
        # Altfel, segment cu segment (în paralel, cu grijă la limitări).
        results: list[Optional[str]] = [None] * len(texts)

        def work(i: int) -> None:
            self.check_cancel()
            results[i] = self._one(texts[i])

        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            list(ex.map(work, range(len(texts))))
        return [r if r is not None else texts[i] for i, r in enumerate(results)]


# --------------------------------------------------------------------------- DeepL
class DeepLEngine(Engine):
    """DeepL API (Free sau Pro). Necesită cheie API."""

    name = "DeepL (cheie API)"
    id = "deepl"
    max_chars = 20000
    max_items = 50

    def __init__(self, api_key: str, formality: str = "default", glossary_entries=None, **kw):
        super().__init__(**kw)
        if not api_key:
            raise TranslationError("Lipsește cheia API DeepL (Setări).")
        import deepl  # import leneș

        client_cls = getattr(deepl, "DeepLClient", None) or deepl.Translator
        self._client = client_cls(api_key)
        self._formality = formality if formality in ("prefer_more", "prefer_less") else None
        self._glossary = None
        self._src = None if self.source_lang in ("auto", "") else self.source_lang.upper()
        if self._src == "NO":
            self._src = "NB"
        if glossary_entries and self._src:
            self._glossary = self._create_glossary(glossary_entries)

    def _create_glossary(self, entries) -> Optional[object]:
        """Încearcă să creeze un glosar DeepL (sursă -> RO). La eșec, continuă fără."""
        try:
            pairs = {e.src: e.ro for e in entries if e.ro and not e.keep
                     and e.lang in ("*", self.source_lang)}
            if not pairs:
                return None
            if hasattr(self._client, "create_multilingual_glossary"):
                from deepl.api_data import MultilingualGlossaryDictionaryEntries
                dicts = [MultilingualGlossaryDictionaryEntries(self._src, "RO", pairs)]
                g = self._client.create_multilingual_glossary("PDFTranslatorRO", dicts)
            else:
                g = self._client.create_glossary("PDFTranslatorRO", source_lang=self._src,
                                                 target_lang="RO", entries=pairs)
            self.log(f"  · glosar DeepL creat ({len(pairs)} termeni)")
            return g
        except Exception as exc:  # noqa: BLE001
            self.log(f"  · glosarul DeepL nu a putut fi creat ({str(exc)[:120]}); continui fără")
            return None

    def translate_batch(self, texts: Sequence[str]) -> list[str]:
        self.check_cancel()
        texts = list(texts)
        if not texts:
            return []

        def call():
            self._pause()
            kwargs = dict(target_lang="RO", source_lang=self._src, preserve_formatting=True)
            if self._formality:
                kwargs["formality"] = self._formality
            if self._glossary is not None:
                kwargs["glossary"] = self._glossary
            res = self._client.translate_text(texts, **kwargs)
            if not isinstance(res, list):
                res = [res]
            return [r.text for r in res]

        return list(_retry(call, cancel=self.cancel, log=self.log))

    def close(self) -> None:
        if self._glossary is not None:
            try:
                if hasattr(self._client, "delete_multilingual_glossary"):
                    self._client.delete_multilingual_glossary(self._glossary)
                else:
                    self._client.delete_glossary(self._glossary)
            except Exception:  # noqa: BLE001
                pass
            self._glossary = None


# --------------------------------------------------------------------------- Claude
_SYSTEM_TRANSLATE = """Ești un traducător tehnic specializat în echipamente electrice (aparataj de joasă tensiune, \
tablouri, cabluri, iluminat, automatizări). Traduci fișe de catalog și fișe tehnice din orice limbă în limba ROMÂNĂ.

Reguli obligatorii:
1. Traducerea trebuie să fie EXACTĂ și COMPLETĂ: fiecare informație din sursă apare în traducere, nimic în plus, \
nimic omis, nimic rezumat sau parafrazat liber. Păstrează ordinea informațiilor.
2. Marcajele de forma ⟦0⟧, ⟦1⟧ ... sunt tokeni protejați (coduri, numere, unități, standarde). Trebuie păstrați \
EXACT, cu același număr și același index, la locul potrivit gramatical. Nu inventa, nu șterge, nu renumerota marcaje.
3. Numerele, codurile de produs, unitățile de măsură și denumirile de standarde rămân identice cu sursa.
4. Folosește terminologia tehnică românească standard (SR EN / IEC) și termenii din glosar când sunt indicați. \
Folosește diacriticele corecte (ă, â, î, ș, ț).
5. Păstrează registrul concis, specific fișelor tehnice (fără propoziții adăugate). Titlurile rămân titluri, \
celulele de tabel rămân scurte.
6. Textul care este deja în română rămâne neschimbat. Numele de mărci și de game de produse rămân neschimbate.
7. Răspunzi DOAR cu JSON valid, fără explicații și fără text în afara JSON-ului.
"""

_SYSTEM_POSTEDIT = _SYSTEM_TRANSLATE + """
Primești pentru fiecare segment textul sursă ("src") și o traducere automată brută ("mt"). Sarcina ta este \
POST-EDITAREA: corectează greșelile de sens, gramatica, acordul, topica și terminologia, folosind contextul tuturor \
segmentelor din lot (ele provin din aceeași pagină). Dacă traducerea automată este deja corectă, păstreaz-o. \
Nu adăuga și nu elimina informații față de "src".
"""


class ClaudeEngine(Engine):
    """Traducere directă sau post-editare contextuală cu modelele Claude (API Anthropic)."""

    name = "Claude (cheie API)"
    id = "claude"
    max_chars = 6000
    max_items = 40

    def __init__(self, api_key: str, model: str = "claude-sonnet-5-5", glossary=None, **kw):
        super().__init__(**kw)
        if not api_key:
            raise TranslationError("Lipsește cheia API Anthropic (Setări).")
        import anthropic  # import leneș

        self._client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=180.0)
        self._model = model or "claude-sonnet-5-5"
        self._glossary = glossary

    # .................................................................. utilitare
    @staticmethod
    def _extract_json(text: str) -> list:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("răspunsul nu conține o listă JSON")
        return json.loads(text[start:end + 1])

    def _ask(self, system: str, user: str, max_tokens: int) -> str:
        def call():
            self._pause()
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        return str(_retry(call, attempts=3, cancel=self.cancel, log=self.log))

    def _glossary_block(self, sources: Sequence[str]) -> str:
        if self._glossary is None:
            return ""
        lines = self._glossary.prompt_lines(sources, self.source_lang)
        if not lines:
            return ""
        return "\nGlosar obligatoriu (sursă => română):\n" + "\n".join(lines) + "\n"

    def _run(self, system: str, items: list[dict], sources: Sequence[str], out_key: str = "ro") -> list[str]:
        lang_hint = "" if self.source_lang in ("auto", "") else f"Limba sursă: {self.source_lang}.\n"
        user = (
            f"{lang_hint}{self._glossary_block(sources)}\n"
            f"Tradu în română fiecare element. Returnează o listă JSON cu obiecte "
            f"{{\"id\": <id>, \"{out_key}\": \"<traducerea>\"}} - exact {len(items)} elemente, aceleași id-uri.\n\n"
            + json.dumps(items, ensure_ascii=False)
        )
        est_tokens = sum(len(json.dumps(i, ensure_ascii=False)) for i in items)
        max_tokens = int(min(16000, max(1500, est_tokens * 1.2)))
        raw = self._ask(system, user, max_tokens)
        data = self._extract_json(raw)
        by_id = {}
        for obj in data:
            if isinstance(obj, dict) and "id" in obj:
                by_id[int(obj["id"])] = str(obj.get(out_key, obj.get("ro", "")))
        out: list[str] = []
        for it in items:
            val = by_id.get(int(it["id"]))
            if val is None or not val.strip():
                raise TranslationError(f"răspuns incomplet pentru segmentul {it['id']}")
            out.append(val.strip())
        return out

    # .................................................................. API publică
    def translate_batch(self, texts: Sequence[str]) -> list[str]:
        self.check_cancel()
        texts = list(texts)
        if not texts:
            return []
        items = [{"id": i, "src": t} for i, t in enumerate(texts)]
        try:
            return self._run(_SYSTEM_TRANSLATE, items, texts)
        except (TranslationError, ValueError, json.JSONDecodeError) as exc:
            if len(texts) == 1:
                raise TranslationError(str(exc))
            self.log(f"  · lot Claude invalid ({str(exc)[:100]}); împart lotul")
            mid = len(texts) // 2
            return self.translate_batch(texts[:mid]) + self.translate_batch(texts[mid:])

    def post_edit(self, sources: Sequence[str], drafts: Sequence[str]) -> list[str]:
        """Corectează traducerile brute folosind contextul lotului. La eroare returnează ciornele."""
        self.check_cancel()
        sources, drafts = list(sources), list(drafts)
        if not sources:
            return []
        items = [{"id": i, "src": s, "mt": d} for i, (s, d) in enumerate(zip(sources, drafts))]
        try:
            return self._run(_SYSTEM_POSTEDIT, items, sources)
        except (TranslationError, ValueError, json.JSONDecodeError) as exc:
            if len(sources) == 1:
                self.log(f"  · post-editarea a eșuat pentru un segment ({str(exc)[:100]}); păstrez traducerea brută")
                return drafts
            mid = len(sources) // 2
            return self.post_edit(sources[:mid], drafts[:mid]) + self.post_edit(sources[mid:], drafts[mid:])


# --------------------------------------------------------------------------- fabrică
def make_engine(settings, glossary=None, cancel: Optional[threading.Event] = None,
                log: Optional[Callable[[str], None]] = None) -> Engine:
    common = dict(source_lang=settings.source_lang, cancel=cancel, log=log,
                  request_delay=float(settings.request_delay or 0.0))
    eid = (settings.engine or "google").lower()
    if eid == "google":
        return GoogleEngine(**common)
    if eid == "deepl":
        return DeepLEngine(api_key=settings.deepl_key.strip(), formality=settings.deepl_formality,
                           glossary_entries=glossary.entries if glossary else None, **common)
    if eid == "claude":
        return ClaudeEngine(api_key=settings.anthropic_key.strip(), model=settings.claude_model,
                            glossary=glossary, **common)
    if eid == "test":
        return TestEngine(**common)
    raise TranslationError(f"Motor necunoscut: {settings.engine}")


ENGINE_CHOICES = [
    ("google", GoogleEngine.name),
    ("deepl", DeepLEngine.name),
    ("claude", ClaudeEngine.name),
    ("test", TestEngine.name),
]
