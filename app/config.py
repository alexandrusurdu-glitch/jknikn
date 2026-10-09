"""Căi de resurse, directorul de configurare al utilizatorului și setările persistente."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

APP_DIR_NAME = "PDFTranslatorRO"


def resource_path(*parts: str) -> Path:
    """Returnează calea către un fișier din folderul `resources`.

    Funcționează atât din sursă, cât și din executabilul PyInstaller (sys._MEIPASS).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent
    return base.joinpath("resources", *parts)


def user_config_dir() -> Path:
    """Folderul în care se salvează setările, glosarul utilizatorului și memoria de traducere."""
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = base / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


SETTINGS_FILE = "settings.json"
USER_GLOSSARY_FILE = "glossary_user.json"
TM_FILE = "translation_memory.sqlite3"


@dataclass
class Settings:
    """Toate opțiunile configurabile din interfață."""

    # Motor de traducere: "google" | "deepl" | "claude" | "test"
    engine: str = "google"
    # Post-editare contextuală cu Claude după traducerea automată
    post_edit: bool = False
    # Chei API
    deepl_key: str = ""
    anthropic_key: str = ""
    claude_model: str = "claude-sonnet-5-5"
    # Limba sursă: "auto" sau cod ISO (en, de, fr, ...)
    source_lang: str = "auto"
    # Formalitate DeepL: default | prefer_more | prefer_less
    deepl_formality: str = "default"
    # Protejarea tokenilor tehnici (numere, unități, coduri, standarde)
    protect_tokens: bool = True
    # Convertește separatorul zecimal în virgulă (1.5 -> 1,5). Implicit NU, pentru exactitate.
    decimal_comma: bool = False
    # Fișiere de ieșire
    out_pdf: bool = True
    out_docx: bool = True
    out_report: bool = True
    out_compare: bool = False
    # Reconstrucție PDF
    expand_boxes: bool = True      # extinde casetele spre dreapta când există spațiu liber
    min_scale_warn: float = 0.6    # sub acest factor de micșorare, segmentul este marcat în raport
    # Pauză între cereri (secunde) - util pentru Google gratuit
    request_delay: float = 0.0
    # Memoria de traducere (cache)
    use_tm: bool = True
    # Ultimul folder de ieșire folosit
    last_out_dir: str = ""
    last_in_dir: str = ""
    # Dimensiune maximă a unui lot trimis motorului (caractere)
    batch_chars: int = 3500
    # Alte opțiuni
    extra: dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------- IO
    @classmethod
    def load(cls) -> "Settings":
        path = user_config_dir() / SETTINGS_FILE
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        obj = cls()
        for key, value in data.items():
            if hasattr(obj, key):
                setattr(obj, key, value)
        return obj

    def save(self) -> None:
        path = user_config_dir() / SETTINGS_FILE
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")


# Modele Claude disponibile în interfață (ID-uri API).
CLAUDE_MODELS = [
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
    "claude-opus-5-5",
]

# Limbi sursă oferite în interfață (cod -> nume afișat). "auto" = detectare automată.
SOURCE_LANGUAGES = {
    "auto": "Detectare automată",
    "en": "Engleză",
    "de": "Germană",
    "fr": "Franceză",
    "it": "Italiană",
    "es": "Spaniolă",
    "pt": "Portugheză",
    "nl": "Olandeză",
    "pl": "Poloneză",
    "cs": "Cehă",
    "sk": "Slovacă",
    "hu": "Maghiară",
    "tr": "Turcă",
    "ru": "Rusă",
    "uk": "Ucraineană",
    "bg": "Bulgară",
    "el": "Greacă",
    "sv": "Suedeză",
    "da": "Daneză",
    "fi": "Finlandeză",
    "no": "Norvegiană",
    "zh": "Chineză",
    "ja": "Japoneză",
    "ko": "Coreeană",
}
