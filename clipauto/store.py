"""Suivi des clips (SQLite) : en attente → approuvé/rejeté → publié."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS clips(
            id INTEGER PRIMARY KEY, created REAL, streamer TEXT, platform TEXT, path TEXT,
            score REAL, detail TEXT, transcript TEXT, status TEXT DEFAULT 'pending',
            post_id TEXT, error TEXT)""")
        self.db.commit()

    def add(self, streamer: str, platform: str, path: str, score: float, detail: dict, transcript: str) -> int:
        cur = self.db.execute(
            "INSERT INTO clips(created,streamer,platform,path,score,detail,transcript) VALUES(?,?,?,?,?,?,?)",
            (time.time(), streamer, platform, path, score, json.dumps(detail), transcript))
        self.db.commit()
        return cur.lastrowid

    def get(self, clip_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()

    def set(self, clip_id: int, **kw) -> None:
        cols = ",".join(f"{k}=?" for k in kw)
        self.db.execute(f"UPDATE clips SET {cols} WHERE id=?", (*kw.values(), clip_id))
        self.db.commit()

    def pending(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM clips WHERE status='pending' ORDER BY id").fetchall()
