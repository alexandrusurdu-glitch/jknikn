"""Generează un PDF de probă asemănător unei fișe tehnice (text fictiv, în engleză)."""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf


def make_sample(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4

    # Antet colorat
    page.draw_rect(pymupdf.Rect(0, 0, 595, 70), color=None, fill=(0.0, 0.33, 0.6))
    page.insert_text((36, 44), "Miniature circuit breaker XB-Line 6 kA", fontsize=20, fontname="helv",
                     color=(1, 1, 1))
    page.insert_text((36, 60), "Product data sheet  |  Reference XB6-C16-2P", fontsize=10, fontname="helv",
                     color=(1, 1, 1))

    # Paragraf descriere
    desc = ("The XB-Line miniature circuit breakers provide protection against overload and short-circuit "
            "for residential and commercial installations. They comply with IEC/EN 60898-1:2019 and are "
            "suitable for DIN rail mounting in distribution boards. The 2-pole version switches both the "
            "phase and the neutral conductor.")
    page.insert_textbox(pymupdf.Rect(36, 90, 559, 150), desc, fontsize=10, fontname="helv", align=0)

    page.insert_text((36, 175), "Technical data", fontsize=14, fontname="hebo", color=(0.0, 0.33, 0.6))

    rows = [
        ("Rated current In", "16 A"),
        ("Rated voltage Ue", "230/400 V AC"),
        ("Rated frequency", "50/60 Hz"),
        ("Breaking capacity Icu", "6 kA"),
        ("Tripping curve", "C (5...10 x In)"),
        ("Number of poles", "2P"),
        ("Degree of protection", "IP20 (IP40 in enclosure)"),
        ("Operating temperature", "-25 °C ... +70 °C"),
        ("Conductor cross section", "1 ... 25 mm² (rigid), 1 ... 16 mm² (flexible)"),
        ("Tightening torque", "2.5 Nm"),
        ("Electrical endurance", "10 000 operating cycles"),
        ("Width in 18 mm modules", "2"),
        ("Weight", "0.245 kg"),
        ("Standards", "IEC/EN 60898-1, IEC 60947-2"),
    ]
    y = 190
    x0, x1, x2 = 36, 250, 559
    page.draw_rect(pymupdf.Rect(x0, y, x2, y + 18), color=None, fill=(0.85, 0.89, 0.95))
    page.insert_text((x0 + 4, y + 13), "Characteristic", fontsize=9, fontname="hebo")
    page.insert_text((x1 + 4, y + 13), "Value", fontsize=9, fontname="hebo")
    page.draw_line((x0, y), (x2, y), width=0.6); y += 18
    for name, value in rows:
        page.draw_line((x0, y), (x2, y), width=0.3)
        page.insert_text((x0 + 4, y + 13), name, fontsize=9, fontname="helv")
        page.insert_text((x1 + 4, y + 13), value, fontsize=9, fontname="helv")
        y += 18
    page.draw_line((x0, y), (x2, y), width=0.6)
    page.draw_line((x0, 190), (x0, y), width=0.6)
    page.draw_line((x1, 190), (x1, y), width=0.3)
    page.draw_line((x2, 190), (x2, y), width=0.6)

    # Notă de siguranță
    y += 24
    page.insert_text((36, y), "WARNING", fontsize=11, fontname="hebo", color=(0.8, 0, 0))
    page.insert_textbox(pymupdf.Rect(36, y + 6, 559, y + 50),
                        "Installation and maintenance must be carried out by qualified personnel only. "
                        "Switch off the power supply before wiring the device. Do not exceed the rated "
                        "operational voltage.", fontsize=9, fontname="helv")
    # Listă accesorii
    y += 70
    page.insert_text((36, y), "Accessories", fontsize=12, fontname="hebo", color=(0.0, 0.33, 0.6))
    acc = ["Auxiliary contact XB-AUX (1 NO + 1 NC), order no. XB-AUX-11",
           "Shunt trip XB-ST, coil voltage 230 V AC, order no. XB-ST-230",
           "Comb busbar 1P, 12 modules, 63 A, order no. XB-BB-12"]
    for i, line in enumerate(acc):
        page.insert_text((46, y + 18 + i * 14), "• " + line, fontsize=9, fontname="helv")

    # Text rotit (etichetă laterală) și subsol
    page.insert_text((580, 500), "Subject to technical changes", fontsize=8, fontname="helv", rotate=90)
    page.insert_text((36, 810), "Page 1 of 1  |  www.example-electric.com  |  support@example-electric.com",
                     fontsize=8, fontname="helv", color=(0.4, 0.4, 0.4))
    page.insert_textbox(pymupdf.Rect(300, 760, 559, 800),
                        "Available in 1P, 2P, 3P and 4P versions.", fontsize=9, fontname="helv", align=2)
    doc.save(str(path))
    return path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sample_datasheet.pdf")
    print(make_sample(out))
