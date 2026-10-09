"""Protejarea tokenilor tehnici înainte de traducere și restaurarea lor după.

Fișele de catalog conțin coduri de produs, numere cu unități de măsură, referințe la
standarde, simboluri electrice etc. Acestea NU trebuie modificate de motorul de traducere.
Le înlocuim cu marcaje de forma ⟦0⟧, ⟦1⟧ ... și le punem la loc după traducere.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

PH_OPEN = "⟦"   # ⟦
PH_CLOSE = "⟧"  # ⟧

# Unități de măsură (cele mai lungi primele, ca să nu fie "tăiate" de alternativele mai scurte).
_UNITS = [
    "dB(A)", "cd/m²", "W/m²", "W/mK", "m/s²", "kbit/s", "Mbit/s", "Gbit/s", "mm/min", "l/min",
    "m³/h", "km/h", "r/min", "min⁻¹", "mm/s", "µm/m", "mm²", "mm³", "cm²", "cm³", "m/s",
    "kvar", "Mvar", "kcal", "mbar", "kbps", "Mbps", "Gbps", "V AC", "V DC", "A AC", "A DC",
    "Baud", "VAC", "VDC", "Vac", "Vdc", "kVA", "MVA", "kWh", "MWh", "mAh", "GHz", "MHz", "kHz",
    "dBA", "rpm", "AWG", "pcs", "buc", "Stk", "ppm", "psi", "kPa", "MPa", "cal", "dpi", "m²",
    "m³", "µm", "nm", "mm", "cm", "dm", "km", "kg", "mg", "ms", "µs", "ns", "min", "kA", "mA",
    "µA", "kV", "mV", "µV", "MW", "kW", "mW", "VA", "var", "Wh", "Ah", "kΩ", "MΩ", "mΩ", "µF",
    "nF", "pF", "mF", "mH", "µH", "kJ", "kN", "Nm", "Pa", "bar", "°C", "°F", "lm", "lx", "cd",
    "ml", "mL", "lb", "oz", "pz", "ft", "kB", "MB", "GB", "px", "Hz", "Ω", "%", "‰", "°",
    "A", "V", "W", "F", "H", "J", "N", "K", "s", "h", "g", "t", "m", "l", "L",
]

# Acronime și simboluri electrice care rămân neschimbate (potrivire exactă, case-sensitive).
KEEP_WORDS = [
    "AC", "DC", "AC/DC", "DC/AC", "RCD", "RCBO", "MCB", "MCCB", "ACB", "SPD", "PLC", "LED",
    "UPS", "PE", "PEN", "RMS", "THD", "PF", "PWM", "HMI", "SCADA", "IoT", "USB", "RS485",
    "RS-485", "RS232", "RS-232", "TCP/IP", "Modbus", "Profibus", "Profinet", "EtherNet/IP",
    "CANopen", "KNX", "DALI", "BACnet", "LAN", "WLAN", "Wi-Fi", "Bluetooth", "I/O", "NO", "NC",
    "SPDT", "DPDT", "SPST", "DPST", "EMC", "EMI", "ESD", "SELV", "PELV", "FELV", "MTBF", "PV",
    "CE", "UKCA", "RoHS", "REACH", "EAC", "CCC", "UL", "CSA", "cULus", "ATEX", "IECEx",
    "Icu", "Ics", "Icn", "Icw", "Icm", "Uimp", "Ui", "Ue", "Ulimp", "Idn", "IΔn", "Isd", "Ir",
    "Ii", "Ig", "tsd", "Ith", "Ithe", "Ie", "Iz", "Ib", "Ip", "Ik", "Ik''", "cos φ", "cosφ",
    "cos phi", "L1", "L2", "L3", "N", "L+", "L-", "DIN", "IP", "IK", "Un", "In",
]

_STANDARD_BODIES = (
    "IEC", "EN", "ISO", "DIN", "VDE", "SR", "STAS", "UL", "CSA", "IEEE", "ANSI", "NEMA", "NF",
    "BS", "CEI", "GB", "JIS", "GOST", "HD", "ETSI", "ITU", "IEC/EN", "EN/IEC", "SR EN", "ÖVE",
    "UNE", "UNI", "NBN", "SN", "PN", "ČSN", "MSZ", "TS", "TR",
)

_URL_RE = r"(?:https?://|www\.)[^\s<>\"')\]]+"
_EMAIL_RE = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
_STANDARD_RE = (
    r"\b(?:" + "|".join(re.escape(b) for b in sorted(_STANDARD_BODIES, key=len, reverse=True)) + r")"
    r"(?:[ /-](?:IEC|EN|ISO|HD|TS|TR|VDE|DIN|CLC))*"
    r"[  ]?\d{2,6}(?:[-–/:.]{1,2}\d{1,6})*(?:[-–/]\d+)*"
    r"(?:\s?(?:Ed\.?\s?\d+))?"
)
# Coduri de produs: conțin cel puțin o cifră și o literă (ex. A9F74206, 5SL6, NSX100F, 230V, IP20).
# Exceptăm ordinalele englezești (1st, 2nd) și construcțiile tip "2-pole" / "4-polig".
_CODE_RE = (
    r"(?<![\w/⟦])"
    r"(?!\d+(?:st|nd|rd|th)\b)"
    r"(?!\d+(?:[.,]\d+)?-[a-zà-ÿ]{3,}\b)"
    r"(?=[A-Za-z0-9/\-._+]*\d)(?=[A-Za-z0-9/\-._+]*[A-Za-z])"
    r"[A-Za-z0-9][A-Za-z0-9/\-._+]*[A-Za-z0-9+²³]"
    r"(?![\w/])"
)
_NUMBER_RE = (
    r"(?<![\w⟦])(?<!\d[.,])[-+±]?\d+(?:[.,   ]\d{3}(?!\d))*(?:[.,]\d+)?(?:/\d+)?"
    r"(?:[  ]?(?:" + "|".join(re.escape(u) for u in _UNITS) + r"))?"
    r"(?![\w])"
)

# Marcaj tolerant: acceptă variante deformate de motorul de traducere ("⟦ 3 ⟧", "[[3]]", "【3】").
_PH_EXACT_RE = re.compile(PH_OPEN + r"\s*(\d+)\s*" + PH_CLOSE)
_PH_LOOSE_RE = re.compile(r"[⟦\[【〔]{1,2}\s*(\d+)\s*[⟧\]】〕]{1,2}")


@dataclass
class Protected:
    """Rezultatul protejării unui segment."""

    text: str                       # textul cu marcaje ⟦n⟧
    tokens: list[str] = field(default_factory=list)   # tokenii originali, în ordinea indexului
    kinds: list[str] = field(default_factory=list)    # tipul fiecărui token (url, code, number ...)

    @property
    def has_translatable_text(self) -> bool:
        """True dacă, după scoaterea tokenilor, mai rămâne text cu litere de tradus."""
        rest = _PH_EXACT_RE.sub(" ", self.text)
        return bool(re.search(r"[^\W\d_]{2,}", rest))


class Protector:
    """Construiește expresia regulată combinată și oferă protect()/restore()."""

    def __init__(self, keep_terms: Iterable[str] = (), protect_numbers: bool = True,
                 decimal_comma: bool = False):
        self.decimal_comma = decimal_comma
        self.protect_numbers = protect_numbers
        keep = sorted({t.strip() for t in keep_terms if t and t.strip()}, key=len, reverse=True)
        keep_words = sorted(set(KEEP_WORDS), key=len, reverse=True)

        parts = [
            ("url", _URL_RE),
            ("email", _EMAIL_RE),
        ]
        if keep:
            parts.append(("keep", r"(?<!\w)(?:" + "|".join(re.escape(k) for k in keep) + r")(?!\w)"))
        parts.append(("standard", _STANDARD_RE))
        parts.append(("word", r"(?<![\w/])(?:" + "|".join(re.escape(k) for k in keep_words) + r")(?![\w/])"))
        if protect_numbers:
            parts.append(("date", r"(?<![\w.,])\d{1,4}[./-]\d{1,2}[./-]\d{1,4}(?![\w.])"))
            parts.append(("code", _CODE_RE))
            parts.append(("number", _NUMBER_RE))
        self._kinds = [k for k, _ in parts]
        self._re = re.compile("|".join(f"(?P<{k}>{p})" for k, p in parts))

    # ------------------------------------------------------------------ protect
    def protect(self, text: str) -> Protected:
        tokens: list[str] = []
        kinds: list[str] = []

        def repl(m: re.Match) -> str:
            kind = m.lastgroup or "token"
            tok = m.group(0)
            # "In" / "Ie" / "Un" sunt și cuvinte uzuale: le protejăm doar în context tehnic
            # (urmate de =, :, cifră, paranteză sau la sfârșitul textului).
            if kind == "word" and tok in {"In", "Ie", "Un", "N", "IP", "IK", "NO", "NC", "CE", "PE"}:
                after = text[m.end():m.end() + 3]
                if not re.match(r"^\s*(?:[=:≤≥<>≈~(/]|\d|$)", after):
                    return tok
            idx = len(tokens)
            tokens.append(tok)
            kinds.append(kind)
            return f"{PH_OPEN}{idx}{PH_CLOSE}"

        protected = self._re.sub(repl, text)
        return Protected(text=protected, tokens=tokens, kinds=kinds)

    # ------------------------------------------------------------------ restore
    def restore(self, translated: str, prot: Protected) -> tuple[str, list[int]]:
        """Pune tokenii la loc. Returnează (text, lista indecșilor care NU au putut fi restaurați)."""
        n = len(prot.tokens)
        seen: set[int] = set()

        def value(idx: int) -> str:
            tok = prot.tokens[idx]
            if self.decimal_comma and prot.kinds[idx] == "number":
                tok = re.sub(r"(?<=\d)\.(?=\d)", ",", tok)
            return tok

        def repl_exact(m: re.Match) -> str:
            idx = int(m.group(1))
            if 0 <= idx < n:
                seen.add(idx)
                return value(idx)
            return m.group(0)

        out = _PH_EXACT_RE.sub(repl_exact, translated)
        missing = [i for i in range(n) if i not in seen]
        if missing:
            def repl_loose(m: re.Match) -> str:
                idx = int(m.group(1))
                if idx in missing:
                    seen.add(idx)
                    return value(idx)
                return m.group(0)
            out = _PH_LOOSE_RE.sub(repl_loose, out)
            missing = [i for i in range(n) if i not in seen]
        # Curățăm eventuale marcaje rămase (deformate complet) ca să nu apară în document.
        out = re.sub(r"[⟦⟧]", "", out)
        return out, missing


# ---------------------------------------------------------------------- QA numeric
_DIGITS_RE = re.compile(r"\d+")


def number_signature(text: str) -> Counter:
    """Multiset-ul grupurilor de cifre dintr-un text (pentru verificarea exactității)."""
    return Counter(_DIGITS_RE.findall(text or ""))


def numbers_match(source: str, target: str) -> tuple[bool, list[str], list[str]]:
    """Compară cifrele din sursă cu cele din traducere. Returnează (ok, lipsă, în plus)."""
    s, t = number_signature(source), number_signature(target)
    missing = sorted((s - t).elements())
    extra = sorted((t - s).elements())
    return (not missing and not extra), missing, extra


def has_letters(text: str) -> bool:
    return bool(re.search(r"[^\W\d_]", text or ""))
