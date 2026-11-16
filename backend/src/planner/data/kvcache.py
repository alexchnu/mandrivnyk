"""Tiny persistent key-value cache (SQLite) for responses of external APIs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class KVCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")

    def get(self, key: str) -> Any | None:
        row = self._db.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for i in range(0, len(keys), 500):
            chunk = keys[i : i + 500]
            marks = ",".join("?" * len(chunk))
            for k, v in self._db.execute(f"SELECT k, v FROM kv WHERE k IN ({marks})", chunk):
                out[k] = json.loads(v)
        return out

    def set_many(self, items: dict[str, Any]) -> None:
        self._db.executemany(
            "INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)",
            [(k, json.dumps(v, ensure_ascii=False)) for k, v in items.items()],
        )
        self._db.commit()
