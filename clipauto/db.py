"""Base SQLite : réglages, streamers, clips, jobs. Un seul fichier = facile à sauvegarder."""
from __future__ import annotations

import copy
import re
import json
import sqlite3
import threading
import time
from pathlib import Path

from .detector import DEFAULT_HYPE, DEFAULT_LAUGH, DEFAULT_WEIGHTS

DEFAULT_SETTINGS = {
    "profile": "equilibre",
    "poll_seconds": 120,
    "record": {"quality": "1080p60,1080p,720p60,720p,best", "segment_seconds": 10, "buffer_minutes": 15},
    "detect": {
        "window_seconds": 10, "baseline_minutes": 10, "threshold": 2.6, "min_signals": 2,
        "cooldown_seconds": 90, "warmup_seconds": 120, "chat_delay_seconds": 8,
        "weights": dict(DEFAULT_WEIGHTS),
        "laugh_words": list(DEFAULT_LAUGH), "hype_words": list(DEFAULT_HYPE), "keywords": [],
        "max_clips_per_hour": 12,
    },
    "clip": {"min_seconds": 30, "max_seconds": 60, "pre_roll": 40, "post_roll": 20,
             "snap_to_sentences": True, "language": "fr", "whisper_model": "small", "auto_render": True,
             "min_viral": 35, "streamer_only": True, "remove_silences": True},
    "style": {
        "preset": "karaoke", "font": "Montserrat Black", "size": 100, "uppercase": True,
        "color": "#FFFFFF", "highlight": "#FFE500", "emphasis_color": "#FF4D4D", "emphasis": True,
        "outline_color": "#000000", "outline": 7, "shadow": 3, "position": 72, "auto_position": True,
        "words_per_line": 3, "pop": True, "max_chars": 18, "clean_punct": True, "remove_fillers": True,
        "box": False, "box_color": "#000000", "box_opacity": 70,
    },
    "layout": {"mode": "blur", "focus": {"x": 0.5}, "split_ratio": 0.5, "cam_position": "top",
               "auto_facecam": True, "pip_size": 0.42, "pip_corner": "tl",
               "facecam": {"x": 0.0, "y": 0.0, "w": 0.3, "h": 0.3},
               "gameplay": {"x": 0.2, "y": 0.0, "w": 0.6, "h": 1.0}},
    "hook": {"enabled": True, "seconds": 3.5, "size": 84, "color": "#FFFFFF", "bg": "#000000"},
    "compilation": {"transition": "fade", "transition_duration": 0.4, "max_each": 20, "clips": 6,
                    "hours": 12},
    "ai": {"enabled": False, "provider": "deepseek", "model": "", "max_calls_per_day": 40, "use_for_cut": True,
           "use_title": True, "ollama_url": "http://localhost:11434"},
    "ai_usage": {},
    "publish": {"auto_publish": False, "social_accounts": [],
                "caption_template": "{title} 😂 #{streamer} #gta #clips"},
}


# Profils de détection : 3 réglages tout faits. Un streamer peut suivre le profil global ou en choisir un.
PROFILES = {
    "prudent": {"label": "Prudent", "desc": "Peu de clips, seulement les très gros moments. Idéal pour les gros streamers au chat très actif.",
                "detect": {"threshold": 4.0, "min_signals": 2, "cooldown_seconds": 150, "max_clips_per_hour": 6},
                "clip": {"min_viral": 50}},
    "equilibre": {"label": "Équilibré", "desc": "Recommandé. Les moments où le chat et le son s'emballent vraiment ensemble.",
                  "detect": {"threshold": 2.6, "min_signals": 2, "cooldown_seconds": 90, "max_clips_per_hour": 12},
                  "clip": {"min_viral": 35}},
    "genereux": {"label": "Généreux", "desc": "Beaucoup de clips, à trier ensuite. Utile pour les petits streamers ou un premier test.",
                 "detect": {"threshold": 1.8, "min_signals": 1, "cooldown_seconds": 60, "max_clips_per_hour": 20},
                 "clip": {"min_viral": 20}},
}


def profile_values(name: str | None) -> dict:
    p = PROFILES.get(name or "")
    return {"detect": dict(p["detect"]), "clip": dict(p["clip"])} if p else {}


def clean_channel(platform: str, raw: str) -> str:
    """« https://www.twitch.tv/michou/clip/xyz?x=1 » → « michou » ; YouTube garde @nom ou l'id de chaîne."""
    c = raw.strip()
    c = re.sub(r"^https?://", "", c)
    c = re.sub(r"^(www\.|m\.)", "", c)
    c = re.sub(r"^(twitch\.tv|kick\.com|youtube\.com)/", "", c, flags=re.I)
    c = c.split("?")[0].split("#")[0].strip("/")
    if platform == "youtube":
        parts = c.split("/")
        if parts[0] in ("channel", "c", "user") and len(parts) > 1:
            return parts[1]
        return parts[0]
    return c.split("/")[0].lstrip("@").lower()


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.c = sqlite3.connect(path, check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.c.executescript("""
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT);
        CREATE TABLE IF NOT EXISTS streamers(id INTEGER PRIMARY KEY, platform TEXT, channel TEXT,
            enabled INTEGER DEFAULT 1, overrides TEXT DEFAULT '{}', created REAL,
            UNIQUE(platform, channel));
        CREATE TABLE IF NOT EXISTS clips(id INTEGER PRIMARY KEY, created REAL, streamer TEXT, platform TEXT,
            source TEXT, path TEXT, thumb TEXT, score REAL, detail TEXT, transcript TEXT,
            words TEXT, edit TEXT, title TEXT, duration REAL, origin TEXT DEFAULT 'live',
            status TEXT DEFAULT 'pending', render_status TEXT DEFAULT 'none', post_id TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, created REAL, kind TEXT, label TEXT,
            status TEXT, progress REAL DEFAULT 0, message TEXT);
        """)
        self.c.commit()
        for r in self.c.execute("SELECT id, platform, channel FROM streamers").fetchall():
            fixed = clean_channel(r["platform"], r["channel"])
            if fixed and fixed != r["channel"]:
                try:
                    self.c.execute("UPDATE streamers SET channel=? WHERE id=?", (fixed, r["id"]))
                except sqlite3.IntegrityError:  # doublon : on supprime le mauvais
                    self.c.execute("DELETE FROM streamers WHERE id=?", (r["id"],))
        self.c.commit()

        # migration : réglages d'avant les profils (seuils calibrés pour l'ancien calcul) → profil Équilibré
        r = self.c.execute("SELECT data FROM settings WHERE id=1").fetchone()
        if r and "profile" not in json.loads(r["data"]):
            self.save_settings({"profile": "equilibre", **profile_values("equilibre")})

    # ---- réglages
    def settings(self) -> dict:
        r = self.c.execute("SELECT data FROM settings WHERE id=1").fetchone()
        return deep_merge(DEFAULT_SETTINGS, json.loads(r["data"]) if r else {})

    def save_settings(self, data: dict) -> dict:
        merged = deep_merge(self.settings(), data)
        with self.lock:
            self.c.execute("INSERT OR REPLACE INTO settings(id,data) VALUES(1,?)", (json.dumps(merged),))
            self.c.commit()
        return merged

    # ---- streamers
    def streamers(self) -> list[dict]:
        rows = self.c.execute("SELECT * FROM streamers ORDER BY id").fetchall()
        return [{**dict(r), "enabled": bool(r["enabled"]), "overrides": json.loads(r["overrides"] or "{}")}
                for r in rows]

    def add_streamer(self, platform: str, channel: str, overrides: dict | None = None) -> int:
        with self.lock:
            cur = self.c.execute(
                "INSERT OR IGNORE INTO streamers(platform,channel,overrides,created) VALUES(?,?,?,?)",
                (platform, clean_channel(platform, channel),
                 json.dumps(overrides or {}), time.time()))
            self.c.commit()
            return cur.lastrowid

    def update_streamer(self, sid: int, **kw) -> None:
        if "overrides" in kw:
            kw["overrides"] = json.dumps(kw["overrides"])
        if "enabled" in kw:
            kw["enabled"] = int(bool(kw["enabled"]))
        self._update("streamers", sid, kw)

    def delete_streamer(self, sid: int) -> None:
        with self.lock:
            self.c.execute("DELETE FROM streamers WHERE id=?", (sid,))
            self.c.commit()

    # ---- clips
    def add_clip(self, **kw) -> int:
        for k in ("detail", "words", "edit"):
            if k in kw and not isinstance(kw[k], str):
                kw[k] = json.dumps(kw[k])
        kw.setdefault("created", time.time())
        cols = ",".join(kw)
        with self.lock:
            cur = self.c.execute(f"INSERT INTO clips({cols}) VALUES({','.join('?' * len(kw))})",
                                 tuple(kw.values()))
            self.c.commit()
            return cur.lastrowid

    def clip(self, cid: int) -> dict | None:
        r = self.c.execute("SELECT * FROM clips WHERE id=?", (cid,)).fetchone()
        return self._clip(r) if r else None

    def clips(self, status: str | None = None, limit: int = 200) -> list[dict]:
        q, args = "SELECT * FROM clips", []
        if status:
            q += " WHERE status=?"
            args.append(status)
        rows = self.c.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
        return [self._clip(r, light=True) for r in rows]

    @staticmethod
    def _clip(r, light=False) -> dict:
        d = dict(r)
        for k in ("detail", "edit") + (() if light else ("words",)):
            d[k] = json.loads(d[k]) if d.get(k) else ({} if k != "words" else [])
        if light:
            d.pop("words", None)
        return d

    def update_clip(self, cid: int, **kw) -> None:
        for k in ("detail", "words", "edit"):
            if k in kw and not isinstance(kw[k], str):
                kw[k] = json.dumps(kw[k])
        self._update("clips", cid, kw)

    def delete_clip(self, cid: int) -> None:
        with self.lock:
            self.c.execute("DELETE FROM clips WHERE id=?", (cid,))
            self.c.commit()

    # ---- jobs (imports, rendus)
    def add_job(self, kind: str, label: str) -> int:
        with self.lock:
            cur = self.c.execute("INSERT INTO jobs(created,kind,label,status) VALUES(?,?,?,'running')",
                                 (time.time(), kind, label))
            self.c.commit()
            return cur.lastrowid

    def update_job(self, jid: int, **kw) -> None:
        self._update("jobs", jid, kw)

    def jobs(self, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.c.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))]

    def _update(self, table: str, rid: int, kw: dict) -> None:
        if not kw:
            return
        with self.lock:
            self.c.execute(f"UPDATE {table} SET {','.join(f'{k}=?' for k in kw)} WHERE id=?",
                           (*kw.values(), rid))
            self.c.commit()
