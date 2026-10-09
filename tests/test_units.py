"""Teste unitare rapide (fără internet): protejarea tokenilor, glosarul, detectarea limbii și
parsarea răspunsurilor Claude.   Rulare:  python -m tests.test_units
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Consolele Windows (cp1252) nu pot afișa diacriticele: evităm UnicodeEncodeError la print.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

from app import engines as eng  # noqa: E402
from app.glossary import Entry, Glossary  # noqa: E402
from app.langdetect_lite import detect_language  # noqa: E402
from app.protect import Protector, numbers_match  # noqa: E402


def test_protect_roundtrip() -> None:
    p = Protector(keep_terms=["Acti 9"])
    cases = [
        "Rated current In: 10...63 A, rated voltage Ue 230/400 V AC 50/60 Hz",
        "Reference A9F74216, according to IEC/EN 60898-1:2019 and EN 60947-2, IP20, -25 °C ... +70 °C",
        "Cross section 1.5 mm² to 25 mm², torque 2.5 Nm, 2-pole version, 1 000 pcs, 12.05.2024",
        "Visit www.se.com/ro or write to support@example.com - Acti 9 range",
    ]
    for text in cases:
        pr = p.protect(text)
        assert pr.tokens, text
        back, missing = p.restore(pr.text, pr)
        assert back == text and not missing, (text, back, missing)
        # marcaje deformate de motor ("[[3]]", "⟦ 3 ⟧") trebuie recunoscute
        mangled = pr.text.replace("⟦", "[[").replace("⟧", "]]")
        back2, missing2 = p.restore(mangled, pr)
        assert back2 == text and not missing2, (text, back2)
    # numere: virgulă zecimală opțională
    p2 = Protector(decimal_comma=True)
    pr = p2.protect("Weight 0.245 kg, code A1.5B")
    back, _ = p2.restore(pr.text, pr)
    assert "0,245 kg" in back and "A1.5B" in back, back
    # segmente fără text de tradus
    assert not p.protect("A9F74216").has_translatable_text
    assert not p.protect("16 A").has_translatable_text
    assert p.protect("Weight 16 A").has_translatable_text
    # ordinalele și "2-pole" rămân traductibile
    pr = p.protect("The 2nd edition, 2-pole version")
    assert "2nd" in pr.text and "-pole" in pr.text, pr.text
    print("protect: OK")


def test_numbers_match() -> None:
    ok, miss, extra = numbers_match("10 A 230 V", "10 A 220 V")
    assert not ok and miss == ["230"] and extra == ["220"]
    assert numbers_match("IP20 6 kA", "6 kA IP20")[0]
    print("numbers_match: OK")


def test_glossary() -> None:
    g = Glossary([
        Entry("en", "circuit breaker", "întrerupător automat"),
        Entry("en", "rated current", "curent nominal"),
        Entry("*", "Acti 9", "Acti 9", keep=True),
        Entry("en", "switch", "întrerupător"),
    ])
    assert g.keep_terms() == ["Acti 9"]
    found = [e.src for e in g.matches("The circuit breaker rated current is 16 A", "en")]
    assert found == ["circuit breaker", "rated current"], found
    missed = g.check("Circuit breaker rated current", "Întrerupătorul automat curentul nominal", "en")
    assert missed == [], [e.src for e in missed]
    missed = g.check("Circuit breaker rated current", "Disjunctor curent nominal", "en")
    assert [e.src for e in missed] == ["circuit breaker"]
    # termenii scurți generici nu produc avertismente
    assert g.check("Switch off", "Opriți", "en") == []
    lines = g.prompt_lines(["circuit breaker Acti 9"], "en")
    assert any("circuit breaker" in ln for ln in lines) and any("Acti 9" in ln for ln in lines)
    print("glossary: OK")


def test_langdetect() -> None:
    assert detect_language("The device is suitable for the protection of cables and is rated for the "
                           "current of the circuit and the voltage of the network.") == "en"
    assert detect_language("Der Leitungsschutzschalter ist für den Schutz von Leitungen und Kabeln "
                           "geeignet und wird auf der Hutschiene montiert.") == "de"
    assert detect_language("Le disjoncteur est destiné à la protection des câbles et des circuits "
                           "dans les installations domestiques et tertiaires.") == "fr"
    assert detect_language("自动断路器用于保护电缆") == "zh"
    assert detect_language("16 A") == "auto"
    print("langdetect: OK")


def test_claude_parsing() -> None:
    e = eng.ClaudeEngine.__new__(eng.ClaudeEngine)
    eng.Engine.__init__(e, source_lang="en")
    e._glossary = None
    e._model = "test"
    calls = {"n": 0}

    def fake_ask(system, user, max_tokens):
        calls["n"] += 1
        return '```json\n[{"id": 0, "ro": "Curent nominal ⟦0⟧"}, {"id": 1, "ro": "Capacitate de rupere ⟦0⟧"}]\n```'

    e._ask = fake_ask  # type: ignore[method-assign]
    out = e.translate_batch(["Rated current ⟦0⟧", "Breaking capacity ⟦0⟧"])
    assert out == ["Curent nominal ⟦0⟧", "Capacitate de rupere ⟦0⟧"], out
    out = e.post_edit(["Rated current ⟦0⟧", "Breaking capacity ⟦0⟧"], ["curent ⟦0⟧", "rupere ⟦0⟧"])
    assert out[0].startswith("Curent nominal")

    def bad_ask(system, user, max_tokens):
        return "nu pot"

    e._ask = bad_ask  # type: ignore[method-assign]
    out = e.post_edit(["Rated current ⟦0⟧"], ["curent ⟦0⟧"])
    assert out == ["curent ⟦0⟧"], "la eroare se păstrează traducerea brută"
    try:
        e.translate_batch(["Rated current ⟦0⟧"])
    except eng.TranslationError:
        pass
    else:
        raise AssertionError("trebuia să ridice TranslationError")
    print("claude parsing: OK")


if __name__ == "__main__":
    test_protect_roundtrip()
    test_numbers_match()
    test_glossary()
    test_langdetect()
    test_claude_parsing()
    print("\nOK - toate testele unitare au trecut.")
