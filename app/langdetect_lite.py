"""Detectare simplă a limbii sursă (fără dependențe externe).

Este folosită doar pentru alegerea termenilor din glosar și pentru raport; motoarele de
traducere își fac propria detectare. Se bazează pe cuvinte frecvente și pe alfabet.
"""

from __future__ import annotations

import re
from collections import Counter

_STOPWORDS: dict[str, set[str]] = {
    "en": {"the", "and", "of", "to", "with", "for", "in", "is", "are", "on", "by", "or", "from",
           "rated", "current", "voltage", "protection", "type", "number", "data", "not", "be"},
    "de": {"der", "die", "das", "und", "mit", "für", "von", "ist", "sind", "nicht", "bei", "auf",
           "oder", "ein", "eine", "nach", "zum", "zur", "technische", "daten", "bemessungs",
           "spannung", "strom", "nennstrom", "schutz", "werden", "kann", "auch"},
    "fr": {"le", "la", "les", "et", "de", "des", "du", "pour", "avec", "est", "sont", "un", "une",
           "sur", "dans", "par", "ou", "au", "aux", "tension", "courant", "protection", "pas"},
    "it": {"il", "la", "le", "gli", "di", "del", "della", "con", "per", "è", "sono", "un", "una",
           "in", "su", "da", "non", "che", "tensione", "corrente", "protezione", "anche"},
    "es": {"el", "la", "los", "las", "de", "del", "con", "para", "es", "son", "un", "una", "en",
           "por", "no", "que", "tensión", "corriente", "protección", "también", "según"},
    "pt": {"o", "a", "os", "as", "de", "do", "da", "dos", "das", "com", "para", "é", "são", "um",
           "uma", "em", "não", "que", "tensão", "corrente", "proteção", "também"},
    "nl": {"de", "het", "een", "en", "van", "met", "voor", "is", "zijn", "op", "niet", "bij",
           "spanning", "stroom", "beveiliging", "ook", "door", "naar", "wordt"},
    "pl": {"i", "w", "z", "na", "do", "nie", "jest", "są", "dla", "oraz", "przy", "się", "lub",
           "napięcie", "prąd", "znamionowy", "ochrona", "typ", "może"},
    "cs": {"a", "v", "s", "na", "do", "pro", "je", "jsou", "nebo", "při", "se", "podle",
           "napětí", "proud", "jmenovitý", "ochrana", "typ", "může"},
    "hu": {"a", "az", "és", "egy", "van", "nem", "hogy", "vagy", "meg", "való", "feszültség",
           "áram", "névleges", "védelem", "típus", "lehet"},
    "tr": {"ve", "bir", "ile", "için", "bu", "da", "de", "olarak", "veya", "gerilim", "akım",
           "anma", "koruma", "tip", "değil"},
    "ro": {"și", "si", "de", "la", "cu", "pentru", "este", "sunt", "un", "o", "în", "in", "pe",
           "din", "sau", "nu", "tensiune", "curent", "nominal", "protecție", "protectie"},
    "sv": {"och", "att", "det", "som", "en", "ett", "för", "med", "är", "på", "av", "till",
           "inte", "spänning", "ström", "märk", "skydd"},
    "da": {"og", "at", "det", "som", "en", "et", "for", "med", "er", "på", "af", "til", "ikke",
           "spænding", "strøm", "mærke", "beskyttelse"},
    "fi": {"ja", "on", "ei", "että", "tai", "sekä", "kanssa", "jännite", "virta", "nimellis",
           "suojaus", "tyyppi", "voi"},
}


def detect_language(text: str) -> str:
    """Returnează codul limbii (ex. "en") sau "auto" dacă nu se poate decide."""
    if not text:
        return "auto"
    sample = text[:20000]
    # Alfabete ne-latine
    if re.search(r"[一-鿿]", sample):
        return "ja" if re.search(r"[぀-ヿ]", sample) else "zh"
    if re.search(r"[가-힯]", sample):
        return "ko"
    if re.search(r"[Ѐ-ӿ]", sample):
        if re.search(r"[іїєґ]", sample.lower()):
            return "uk"
        if re.search(r"[ъщ]", sample.lower()) and not re.search(r"[ыэ]", sample.lower()):
            return "bg"
        return "ru"
    if re.search(r"[Ͱ-Ͽ]", sample):
        return "el"
    if re.search(r"[؀-ۿ]", sample):
        return "ar"

    words = re.findall(r"[^\W\d_]+", sample.lower())
    if len(words) < 5:
        return "auto"
    counts = Counter(words)
    scores: dict[str, float] = {}
    for lang, sw in _STOPWORDS.items():
        scores[lang] = sum(counts[w] for w in sw)
    best_lang, best = max(scores.items(), key=lambda kv: kv[1])
    ranked = sorted(scores.values(), reverse=True)
    second = ranked[1] if len(ranked) > 1 else 0
    # Cerem un minim de dovezi și o diferență clară față de locul 2
    if best < max(3, 0.01 * len(words)) or best < 1.25 * second:
        return "auto"
    return best_lang
