"""Détection temps réel des moments forts = fusion de signaux normalisés.

Signaux :
  chat_rate        messages / seconde
  unique_chatters  personnes distinctes qui écrivent (résiste au spam)
  laugh_emotes     messages contenant un mot/emote de rire (liste réglable)
  hype_emotes      messages contenant un mot/emote de hype (liste réglable)
  keywords         messages contenant un de VOS mots-clés (ex. « clip », nom d'un perso GTA…)
  audio            pic de volume (percentile 90 de la fenêtre, en dB)

Chaque signal est comparé à l'historique récent DU MÊME stream (médiane + MAD) :
on mesure « combien c'est anormal pour ce streamer », pas une valeur absolue.
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field

import numpy as np

DEFAULT_LAUGH = ["kekw", "lul", "lol", "lmao", "lmfao", "omegalul", "icant", "xd", "xdd", "pepelaugh",
                 "mdr", "ptdr", "jpp", "😂", "🤣", "💀", "😭", "haha"]
DEFAULT_HYPE = ["pog", "pogchamp", "poggers", "pogu", "w", "ww", "clip", "clipit", "omg", "wtf",
                "🔥", "😱", "😳", "monkas", "sheesh", "insane", "no way", "wow", "gg"]
DEFAULT_WEIGHTS = {"chat_rate": 1.0, "unique_chatters": 1.2, "laugh_emotes": 1.5,
                   "hype_emotes": 0.8, "keywords": 1.0, "audio": 1.0}
_TOKEN = re.compile(r"[\w']+|[^\w\s]", re.UNICODE)


class Lexicon:
    """Listes de mots réglables. Un mot finissant par * est un préfixe (ex. « haha* », « ptdr* »)."""

    def __init__(self, laugh=None, hype=None, keywords=None):
        self.laugh = self._prep(laugh if laugh is not None else DEFAULT_LAUGH)
        self.hype = self._prep(hype if hype is not None else DEFAULT_HYPE)
        self.keywords = self._prep(keywords or [])

    @staticmethod
    def _prep(words):
        exact, prefix, phrases = set(), [], []
        for w in words:
            w = str(w).strip().lower()
            if not w:
                continue
            if " " in w:
                phrases.append(w)
            elif w.endswith("*"):
                prefix.append(w[:-1])
            else:
                exact.add(w)
        return exact, tuple(prefix), phrases

    @staticmethod
    def _hit(lex, toks, low) -> int:
        exact, prefix, phrases = lex
        return int(any(t in exact or (prefix and t.startswith(prefix)) for t in toks)
                   or any(p in low for p in phrases))

    def classify(self, text: str) -> tuple[int, int, int]:
        low = text.lower()
        toks = [t for t in _TOKEN.findall(low)]
        # « hahaha », « ptdrrr » : rires allongés reconnus sans les lister
        laugh = self._hit(self.laugh, toks, low) or int(any(t.startswith(("haha", "ptdr", "mdr")) for t in toks))
        return laugh, self._hit(self.hype, toks, low), self._hit(self.keywords, toks, low)


_default_lex = Lexicon()


def classify(text: str) -> tuple[int, int]:
    laugh, hype, _ = _default_lex.classify(text)
    return laugh, hype


# plus petite « unité » significative par signal : évite qu'un seul message
# sur un historique à zéro donne un score énorme
FLOORS = {"chat_rate": 0.3, "unique_chatters": 2.0, "laugh_emotes": 2.0, "hype_emotes": 2.0,
          "keywords": 1.0, "audio": 1.5}


def robust_z(x: float, hist: np.ndarray, floor: float = 1.0) -> float:
    if len(hist) < 5:
        return 0.0
    med = float(np.median(hist))
    mad = float(np.median(np.abs(hist - med))) * 1.4826
    z = (x - med) / max(mad, 0.25 * abs(med), floor)
    return float(np.clip(z, -10, 10))


@dataclass
class Trigger:
    t: float
    score: float
    detail: dict


@dataclass
class Detector:
    window: int = 10
    baseline_s: int = 600
    threshold: float = 2.0
    cooldown: int = 90
    warmup: int = 120
    min_signals: int = 2
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    lexicon: Lexicon = field(default_factory=Lexicon)

    def __post_init__(self):
        self.msgs: deque = deque()
        self.audio: deque = deque()
        self.hist: dict[str, deque] = {k: deque(maxlen=max(self.baseline_s // self.window, 6))
                                       for k in DEFAULT_WEIGHTS}
        self.t_start: float | None = None
        self.last_trigger = 0.0
        self.timeline: deque = deque(maxlen=180)  # (t, score, z) pour le graphe live

    def add_message(self, t: float, user: str, text: str) -> None:
        laugh, hype, kw = self.lexicon.classify(text)
        self.msgs.append((t, user.lower(), laugh, hype, kw))

    def add_audio(self, t: float, rms_db: float) -> None:
        self.audio.append((t, rms_db))

    def features(self, now: float, reaction: float = 0.0) -> dict[str, float]:
        """Chat sur [now-window, now] ; audio sur la même fenêtre décalée de `reaction` secondes
        (le chat réagit APRÈS ce qui se passe à l'image : l'audio du moment est plus tôt)."""
        lo, hi = now - self.window, now
        m = [x for x in self.msgs if lo <= x[0] < hi]
        while self.msgs and self.msgs[0][0] < lo - 180:
            self.msgs.popleft()
        while self.audio and self.audio[0][0] < lo - reaction - 180:
            self.audio.popleft()
        aud = [a for t, a in self.audio if lo - reaction <= t < hi - reaction]
        return {
            "chat_rate": len(m) / self.window,
            "unique_chatters": float(len({x[1] for x in m})),
            "laugh_emotes": float(sum(x[2] for x in m)),
            "hype_emotes": float(sum(x[3] for x in m)),
            "keywords": float(sum(x[4] for x in m)),
            "audio": float(np.percentile(aud, 90)) if aud else float("nan"),
        }

    def step(self, now: float, reaction: float = 0.0) -> Trigger | None:
        """`now` = heure du chat analysé. Le moment fort à l'image est à `now - reaction`."""
        if self.t_start is None:
            self.t_start = now
        f = self.features(now, reaction)
        base = {}
        zs, score, wsum = {}, 0.0, 0.0
        for k, w in self.weights.items():
            v = f.get(k, float("nan"))
            if w <= 0 or np.isnan(v):
                continue
            hist = np.array(self.hist[k], dtype=float)
            z = robust_z(v, hist, FLOORS.get(k, 1.0))
            base[k] = round(float(np.median(hist)), 2) if len(hist) else None
            # un mot-clé perso compte même si l'historique est vide (événement rare = fort)
            if k == "keywords" and v > 0 and len(hist) and np.median(hist) == 0:
                z = max(z, min(2.0 + v, 10.0))
            self.hist[k].append(v)
            zs[k] = round(float(z), 2)
            score += w * max(z, 0.0)
            wsum += w
        score = score / wsum if wsum else 0.0
        self.timeline.append((now, round(score, 2), zs))
        rising = sum(z > 1.5 for z in zs.values())
        if (now - self.t_start >= self.warmup and score >= self.threshold and rising >= self.min_signals
                and now - self.last_trigger > self.cooldown):
            self.last_trigger = now
            curve = [[round(t - now, 1), sc] for t, sc, _ in list(self.timeline)[-30:]]
            return Trigger(now - reaction, round(score, 2),
                           {"z": zs, "raw": {k: (None if np.isnan(v) else round(v, 2)) for k, v in f.items()},
                            "base": base, "threshold": self.threshold, "curve": curve,
                            "weights": dict(self.weights), "reaction": reaction})
        return None
