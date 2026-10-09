"""Glosar terminologic: încărcare, combinare (implicit + utilizator), verificare și export."""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from .config import resource_path, user_config_dir, USER_GLOSSARY_FILE


@dataclass
class Entry:
    lang: str       # limba sursă ("en", "de", ... sau "*" pentru orice)
    src: str        # termenul sursă
    ro: str         # traducerea în română
    keep: bool = False   # True = termenul nu se traduce (se păstrează identic)

    def key(self) -> tuple[str, str]:
        return (self.lang.lower().strip() or "*", self.src.lower().strip())


def _strip_diacritics(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _stem(word: str) -> str:
    """Rădăcină aproximativă (fără diacritice, primele 5 litere) pentru potrivire tolerantă la flexiune."""
    w = _strip_diacritics(word.lower())
    w = re.sub(r"[^a-z0-9]", "", w)
    return w[:5] if len(w) > 5 else w


class Glossary:
    def __init__(self, entries: Iterable[Entry] = ()):
        self.entries: list[Entry] = list(entries)
        self._compiled: dict[str, list[tuple[Entry, re.Pattern]]] = {}

    # ------------------------------------------------------------------ încărcare
    @staticmethod
    def _load_file(path: Path) -> list[Entry]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        items = data.get("entries", data) if isinstance(data, dict) else data
        out: list[Entry] = []
        for it in items or []:
            if not isinstance(it, dict) or not it.get("src"):
                continue
            out.append(Entry(
                lang=str(it.get("lang", "*") or "*"),
                src=str(it["src"]).strip(),
                ro=str(it.get("ro", "")).strip(),
                keep=bool(it.get("keep", False)),
            ))
        return out

    @classmethod
    def load(cls) -> "Glossary":
        """Glosarul implicit (din resources) peste care se aplică glosarul utilizatorului."""
        merged: dict[tuple[str, str], Entry] = {}
        for e in cls._load_file(resource_path("glossary_default.json")):
            merged[e.key()] = e
        for e in cls._load_file(user_config_dir() / USER_GLOSSARY_FILE):
            merged[e.key()] = e
        return cls(merged.values())

    @classmethod
    def load_user_only(cls) -> list[Entry]:
        return cls._load_file(user_config_dir() / USER_GLOSSARY_FILE)

    @staticmethod
    def save_user(entries: Iterable[Entry]) -> Path:
        path = user_config_dir() / USER_GLOSSARY_FILE
        payload = {"entries": [asdict(e) for e in entries]}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    # ------------------------------------------------------------------ CSV
    @staticmethod
    def import_csv(path: Path) -> list[Entry]:
        """CSV cu coloanele: lang, src, ro[, keep]. Separator , sau ; (detectat automat)."""
        text = path.read_text(encoding="utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(text.splitlines(), dialect))
        out: list[Entry] = []
        for row in rows:
            if not row or all(not c.strip() for c in row):
                continue
            cells = [c.strip() for c in row]
            if cells[0].lower() in {"lang", "limba", "limbă"}:
                continue  # antet
            if len(cells) == 2:
                lang, src, ro, keep = "*", cells[0], cells[1], ""
            else:
                lang, src, ro = cells[0] or "*", cells[1], cells[2] if len(cells) > 2 else ""
                keep = cells[3] if len(cells) > 3 else ""
            if src:
                out.append(Entry(lang=lang, src=src, ro=ro or src,
                                 keep=keep.lower() in {"1", "true", "da", "yes", "x"}))
        return out

    @staticmethod
    def export_csv(entries: Iterable[Entry], path: Path) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["lang", "src", "ro", "keep"])
            for e in entries:
                w.writerow([e.lang, e.src, e.ro, "1" if e.keep else ""])

    # ------------------------------------------------------------------ utilizare
    def invalidate(self) -> None:
        """De apelat după modificarea listei de intrări (resetează expresiile compilate)."""
        self._compiled.clear()

    def keep_terms(self) -> list[str]:
        return [e.src for e in self.entries if e.keep]

    def _for_lang(self, lang: str) -> list[tuple[Entry, re.Pattern]]:
        lang = (lang or "*").lower()
        if lang not in self._compiled:
            items: list[tuple[Entry, re.Pattern]] = []
            for e in self.entries:
                if e.keep or not e.ro:
                    continue
                if e.lang not in ("*", lang) and lang != "*":
                    continue
                pat = re.compile(r"(?<!\w)" + re.escape(e.src) + r"(?!\w)", re.IGNORECASE)
                items.append((e, pat))
            # termenii lungi primii, ca "circuit breaker" să fie preferat lui "breaker"
            items.sort(key=lambda t: len(t[0].src), reverse=True)
            self._compiled[lang] = items
        return self._compiled[lang]

    def matches(self, source: str, lang: str) -> list[Entry]:
        """Termenii din glosar care apar în textul sursă."""
        found: list[Entry] = []
        covered = source
        for e, pat in self._for_lang(lang):
            if pat.search(covered):
                found.append(e)
                covered = pat.sub(" ", covered)  # evităm sub-termenii deja acoperiți
        return found

    def check(self, source: str, target: str, lang: str) -> list[Entry]:
        """Termenii prezenți în sursă a căror traducere din glosar NU se regăsește (aproximativ) în țintă."""
        missed: list[Entry] = []
        target_stems = {_stem(w) for w in re.findall(r"[^\W\d_]+", target)}
        for e in self.matches(source, lang):
            # Verificăm doar termenii specifici (compuși sau lungi); cuvintele generice scurte
            # ("switch", "load", "phase") au prea multe traduceri corecte și ar genera zgomot.
            if " " not in e.src.strip() and len(e.src) < 8:
                continue
            words = [w for w in re.findall(r"[^\W\d_]+", e.ro) if len(w) >= 4]
            if not words:
                continue
            # acceptăm oricare dintre variantele separate prin "/" sau paranteze
            main = re.split(r"[(/]", e.ro)[0]
            words = [w for w in re.findall(r"[^\W\d_]+", main) if len(w) >= 4] or words
            if not all(_stem(w) in target_stems for w in words):
                missed.append(e)
        return missed

    def prompt_lines(self, sources: Iterable[str], lang: str, limit: int = 80) -> list[str]:
        """Liniile de glosar relevante pentru un lot de segmente (pentru promptul LLM)."""
        seen: dict[str, Entry] = {}
        for s in sources:
            for e in self.matches(s, lang):
                seen.setdefault(e.src.lower(), e)
            if len(seen) >= limit:
                break
        lines = [f"- {e.src} => {e.ro}" for e in list(seen.values())[:limit]]
        keeps = [k for k in self.keep_terms() if any(k in s for s in sources)]
        if keeps:
            lines.append("- NU se traduc (rămân identice): " + ", ".join(sorted(set(keeps))))
        return lines
