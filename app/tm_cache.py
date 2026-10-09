"""Memorie de traducere (cache) în SQLite: evită retraducerea segmentelor identice.

Fișele de catalog repetă foarte des aceleași texte ("Rated current", "Order no." ...),
așa că memoria reduce mult timpul și costul, și garantează consecvența traducerilor.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from .config import user_config_dir, TM_FILE


class TranslationMemory:
    def __init__(self, path: Optional[Path] = None, enabled: bool = True):
        self.enabled = enabled
        self.path = path or (user_config_dir() / TM_FILE)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        if enabled:
            try:
                self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
                self._conn.execute(
                    "CREATE TABLE IF NOT EXISTS tm ("
                    " key TEXT PRIMARY KEY, engine TEXT, src TEXT, tgt TEXT, created REAL)"
                )
                self._conn.commit()
            except Exception:
                self._conn = None
                self.enabled = False

    @staticmethod
    def _key(engine: str, text: str) -> str:
        return hashlib.sha1(f"{engine}\x00{text}".encode("utf-8")).hexdigest()

    def get(self, engine: str, text: str) -> Optional[str]:
        if not self._conn:
            return None
        with self._lock:
            row = self._conn.execute("SELECT tgt FROM tm WHERE key=?", (self._key(engine, text),)).fetchone()
        return row[0] if row else None

    def put(self, engine: str, text: str, target: str) -> None:
        if not self._conn or not target:
            return
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO tm(key, engine, src, tgt, created) VALUES (?,?,?,?,?)",
                (self._key(engine, text), engine, text, target, time.time()),
            )
            self._conn.commit()

    def count(self) -> int:
        if not self._conn:
            return 0
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM tm").fetchone()[0]

    def clear(self) -> None:
        if not self._conn:
            return
        with self._lock:
            self._conn.execute("DELETE FROM tm")
            self._conn.commit()

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
