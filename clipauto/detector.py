"""Étape 3 : « analyse de sentiment » temps réel = fusion de signaux.

Signaux (cités dans la vidéo, + idées reprises de Clips Kitty / HighlightMiner) :
  - chat_rate        : messages par seconde (hausse d'activité du chat)
  - unique_chatters  : nb de personnes distinctes qui écrivent (anti-spam, plus fiable)
  - laugh_emotes     : KEKW, LUL, 😂, 💀… (rires)
  - hype_emotes      : Pog, W, 🔥, CLIP… (moments forts)
  - audio            : pics de volume / rafales (cris, rires, explosions)

Chaque signal est normalisé par rapport au stream lui-même (médiane + MAD sur les
dernières minutes) : un petit stream calme et un gros stream bruyant produisent
tous les deux des pics exploitables. Le score fusionné déclenche un clip.
"""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

LAUGH = {"kekw", "lul", "lol", "lmao", "lmfao", "omegalul", "icant", "xd", "xdd", "pepelaugh",
         "kappa", "mdr", "ptdr", "jpp", "😂", "🤣", "💀", "😭", "haha", "hahaha", "aahahah"}
HYPE = {"pog", "pogchamp", "poggers", "pogu", "w", "ww", "www", "clip", "clipit", "omg", "wtf",
        "🔥", "😱", "😳", "monkas", "ez", "sheesh", "gg", "insane", "no way", "noway", "wow"}
_TOKEN = re.compile(r"[\w']+|[^\w\s]", re.UNICODE)


def classify(text: str) -> tuple[int, int]:
    toks = [t.lower() for t in _TOKEN.findall(text)]
    low = text.lower()
    laugh = sum(t in LAUGH or t.startswith("haha") or t.startswith("ptdr") for t in toks)
    hype = sum(t in HYPE for t in toks) + ("no way" in low)
    return int(laugh > 0), int(hype > 0)


def robust_z(x: float, hist: np.ndarray) -> float:
    if len(hist) < 5:
        return 0.0
    med = float(np.median(hist))
    mad = float(np.median(np.abs(hist - med))) * 1.4826
    return (x - med) / max(mad, 0.5 * max(med, 1e-3), 1e-3)


@dataclass
class Trigger:
    t: float               # heure murale du pic
    score: float
    detail: dict


@dataclass
class Detector:
    window: int = 10
    baseline_s: int = 600
    threshold: float = 2.0
    cooldown: int = 90
    warmup: int = 120
    weights: dict = field(default_factory=lambda: {"chat_rate": 1.0, "unique_chatters": 1.2,
                                                   "laugh_emotes": 1.5, "hype_emotes": 0.8, "audio": 1.0})

    def __post_init__(self):
        self.msgs: deque = deque()                 # (t, user, laugh, hype)
        self.audio: deque = deque()                # (t, rms_db)
        self.hist: dict[str, deque] = {k: deque(maxlen=self.baseline_s // self.window) for k in self.weights}
        self.t_start: float | None = None
        self.last_trigger = 0.0

    def add_message(self, t: float, user: str, text: str) -> None:
        laugh, hype = classify(text)
        self.msgs.append((t, user.lower(), laugh, hype))

    def add_audio(self, t: float, rms_db: float) -> None:
        self.audio.append((t, rms_db))

    def features(self, now: float) -> dict[str, float]:
        lo = now - self.window
        while self.msgs and self.msgs[0][0] < lo:
            self.msgs.popleft()
        while self.audio and self.audio[0][0] < lo:
            self.audio.popleft()
        m = list(self.msgs)
        aud = [a for _, a in self.audio]
        return {
            "chat_rate": len(m) / self.window,
            "unique_chatters": float(len({u for _, u, _, _ in m})),
            "laugh_emotes": float(sum(l for *_, l, _ in m)),
            "hype_emotes": float(sum(h for *_, h in m)),
            # pic de volume : percentile 90 de la fenêtre (rafales de cris/rires)
            "audio": float(np.percentile(aud, 90)) if aud else float("nan"),
        }

    def step(self, now: float | None = None) -> Trigger | None:
        """À appeler toutes les `window` secondes."""
        now = now or time.time()
        if self.t_start is None:
            self.t_start = now
        f = self.features(now)
        zs, score = {}, 0.0
        for k, w in self.weights.items():
            v = f.get(k, float("nan"))
            if np.isnan(v):
                continue
            z = robust_z(v, np.array(self.hist[k], dtype=float))
            self.hist[k].append(v)
            zs[k] = round(z, 2)
            score += w * max(z, 0.0)
        score /= max(sum(self.weights.values()), 1e-9)
        # il faut au moins 2 signaux qui montent ensemble (évite le spam d'un seul bot)
        rising = sum(z > 1.5 for z in zs.values())
        if (now - self.t_start > self.warmup and score >= self.threshold and rising >= 2
                and now - self.last_trigger > self.cooldown):
            self.last_trigger = now
            return Trigger(now, round(score, 2), {"z": zs, "raw": f})
        return None
