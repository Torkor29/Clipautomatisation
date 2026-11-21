"""Analyse de la pertinence d'un clip à partir de ce qui est DIT (gratuit, local, sans IA payante).

Chaque critère produit une raison lisible (« Commence par une question 🎣 ») pour que
l'utilisateur comprenne pourquoi un clip a été gardé ou écarté.

Option : un « juge IA » (Gemini ou Ollama local) peut donner un avis en plus, avec un
plafond d'appels par jour. Il est DÉSACTIVÉ par défaut.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import urllib.request

log = logging.getLogger(__name__)

EMOTION = {
    # FR
    "putain", "wesh", "frère", "frérot", "gros", "zebi", "sah", "dingue", "dinguerie", "incroyable", "jamais",
    "mdr", "ptdr", "oh", "ah", "non", "attends", "attend", "quoi", "comment", "sérieux", "sérieusement", "fou",
    "folie", "malade", "choqué", "choquant", "ouf", "énorme", "abusé", "abuse", "trop", "nul", "merde", "bordel",
    "honte", "pitié", "aïe", "chaud", "grave", "omg", "wtf", "arrête", "arrêtez", "regarde", "regardez", "vas-y",
    "allez", "bravo", "gagné", "perdu", "mort", "tué", "police", "flic", "braquage", "argent", "million",
    # EN
    "bro", "dude", "insane", "crazy", "what", "wait", "no", "yes", "oh", "god", "fuck", "shit", "damn", "holy",
    "never", "dead", "won", "lost", "money", "cops", "run", "omg",
}
HOOK_START = {"attends", "regarde", "regardez", "écoute", "écoutez", "non", "quoi", "comment", "pourquoi",
              "jamais", "frère", "wesh", "oh", "wait", "what", "bro", "how", "why", "no", "imagine"}
FILLERS = {"euh", "heu", "hum", "bah", "ben", "hein", "um", "uh", "erm"}
_WORD = re.compile(r"[\w'’-]+", re.UNICODE)


def _clean(w: str) -> str:
    return re.sub(r"[^\w'’-]", "", w.lower())


def analyze_text(words: list[dict], t0: float, t1: float, keywords: list[str] | None = None) -> dict:
    """Score 0-100 + raisons. `words` en temps source, on analyse [t0, t1]."""
    words = [w for w in words if not w.get("skip")]  # on n'analyse que ce que dit le streamer
    kept = [w for w in words if t0 <= w["s"] < t1]
    dur = max(t1 - t0, 1e-3)
    reasons: list[tuple[int, str]] = []  # (points, texte)
    flags: list[str] = []
    if not kept:
        return {"score": 15, "reasons": [], "flags": ["Personne ne parle dans ce passage 🔇"], "stats": {}}

    text = " ".join(w["w"] for w in kept)
    toks = [_clean(w["w"]) for w in kept]
    n = len(kept)
    wps = n / dur
    speech = sum(w["e"] - w["s"] for w in kept)
    gaps = [b["s"] - a["e"] for a, b in zip(kept, kept[1:])]
    long_sil = sum(g for g in gaps if g > 1.5)
    kw = {k.lower().rstrip("*") for k in (keywords or []) if k}

    # 1. accroche : les 3 premières secondes
    first = [w for w in kept if w["s"] < t0 + 3]
    first_txt = " ".join(w["w"] for w in first)
    if first and (_clean(first[0]["w"]) in HOOK_START or "?" in first_txt or "!" in first_txt):
        reasons.append((14, f"Accroche forte dès le début : « {first_txt[:50]} » 🎣"))
    elif first and kept[0]["s"] - t0 < 0.8:
        reasons.append((6, "Ça parle dès la première seconde (pas de blanc au début)"))
    else:
        flags.append("Début un peu mou : rien de dit dans la 1re seconde")

    # 2. émotion / réaction
    emo = [t for t in toks if t in EMOTION]
    if len(emo) >= 3:
        pts = min(6 + 2 * len(emo), 22)
        reasons.append((pts, f"Langage très émotionnel ({len(emo)} mots : {', '.join(sorted(set(emo))[:6])}) 🔥"))
    elif emo:
        reasons.append((4, f"Un peu d'émotion ({', '.join(sorted(set(emo)))})"))
    excl = text.count("!") + text.count("?")
    if excl >= 3:
        reasons.append((min(3 * excl, 12), f"{excl} questions / exclamations : échange vivant"))
    rep = sum(1 for a, b in zip(toks, toks[1:]) if a == b and len(a) > 1)
    if rep >= 2:
        reasons.append((6, "Répétitions typiques d'une réaction (« non non non », « attends attends ») 😱"))
    laughs = sum(t.startswith(("haha", "hihi", "mdr", "ptdr", "lol")) for t in toks)
    if laughs:
        reasons.append((8, "On entend des rires 😂"))

    # 3. rythme
    if 2.2 <= wps <= 5.5:
        reasons.append((10, f"Débit dynamique ({wps:.1f} mots/s)"))
    elif wps < 1.2:
        flags.append(f"Peu de paroles ({wps:.1f} mots/s) : à garder seulement si l'action à l'image suffit")
    if long_sil > dur * 0.25:
        flags.append(f"{long_sil:.0f} s de silences longs : pense à les couper ✂️")
    else:
        reasons.append((6, "Peu de temps morts"))

    # 4. cohérence : début et fin propres
    before = [w for w in words if w["e"] <= t0 + 0.05]
    clean_start = not before or before[-1]["w"].strip()[-1:] in ".?!" or kept[0]["s"] - before[-1]["e"] > 0.5
    clean_end = kept[-1]["w"].strip()[-1:] in ".?!" or not [w for w in words if t1 <= w["s"] < t1 + 0.6]
    if clean_start and clean_end:
        reasons.append((10, "Histoire complète : commence et finit sur une phrase entière"))
    else:
        if not clean_start:
            flags.append("Commence au milieu d'une phrase")
        if not clean_end:
            flags.append("Se termine au milieu d'une phrase")
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) >= 3]
    if len(sentences) >= 3:
        reasons.append((4, f"{len(sentences)} phrases : il se passe quelque chose"))

    # 5. mots-clés perso
    hits = sorted({t for t in toks if any(t.startswith(k) for k in kw)}) if kw else []
    if hits:
        reasons.append((min(8 * len(hits), 16), f"Mots-clés trouvés : {', '.join(hits)} 🎯"))

    # 6. durée
    if 20 <= dur <= 50:
        reasons.append((6, f"Durée idéale pour TikTok / Shorts ({dur:.0f} s)"))
    elif dur > 70:
        flags.append(f"Long ({dur:.0f} s) : les clips de 25-45 s performent mieux")

    raw = sum(p for p, _ in reasons) - 6 * len(flags)
    score = int(round(100 * (1 - math.exp(-max(raw, 0) / 45))))
    return {"score": score, "reasons": [r for _, r in sorted(reasons, reverse=True)], "flags": flags,
            "stats": {"words": n, "wps": round(wps, 2), "speech_ratio": round(speech / dur, 2),
                      "emotion_words": len(emo), "silence_s": round(long_sil, 1)}}


def signal_score(score: float) -> int:
    """Score de la détection live (fusion des z-scores) → 0-100."""
    return int(round(100 * (1 - math.exp(-max(score, 0) / 2))))


SIGNAL_LABELS = {"chat_rate": "Messages dans le chat", "unique_chatters": "Viewers différents qui écrivent",
                 "laugh_emotes": "Messages qui rient (KEKW, 😂, mdr…)", "hype_emotes": "Messages de hype (Pog, W, 🔥…)",
                 "keywords": "Vos mots-clés dans le chat", "audio": "Volume sonore (dB)"}


def explain_signals(detail: dict) -> list[dict]:
    """Phrases du type « Messages dans le chat : 42 au lieu de 9 habituellement (×4.7) »."""
    out = []
    raw, base, z = detail.get("raw") or {}, detail.get("base") or {}, detail.get("z") or {}
    for k, label in SIGNAL_LABELS.items():
        if k not in z:
            continue
        v, b = raw.get(k), base.get(k)
        if k == "chat_rate" and v is not None:
            v, b = v * 10, (b * 10 if b is not None else None)
            label += " (par 10 s)"
        ratio = (v / b) if (v is not None and b) else None
        out.append({"key": k, "label": label, "value": v, "normal": b, "z": z[k],
                    "ratio": round(ratio, 1) if ratio else None, "strong": z[k] >= 1.5})
    return sorted(out, key=lambda x: -x["z"])


def combine(signal: int | None, text: int, llm: int | None) -> int:
    parts = [(signal, 0.5), (text, 0.35 if signal is not None else 0.7), (llm, 0.3)]
    tot = sum(w for v, w in parts if v is not None)
    return int(round(sum(v * w for v, w in parts if v is not None) / tot))


# ------------------------------------------------------------------ juge IA optionnel
PROMPT = """Tu es un expert TikTok/Shorts. Voici la transcription d'un extrait de live {platform} de {streamer}.
Note de 0 à 100 son potentiel viral (accroche, émotion, chute, compréhensible sans contexte).
Réponds UNIQUEMENT en JSON : {{"score": int, "title": "titre accrocheur < 60 caractères", "reason": "1 phrase", "keep": true|false}}
Transcription : \"\"\"{text}\"\"\""""


def llm_judge(text: str, streamer: str, platform: str, cfg: dict, usage: dict) -> dict | None:
    """Avis IA simple (score + titre) quand le « monteur IA » n'est pas utilisé."""
    from .llm import call_json
    if not text.strip():
        return None
    d = call_json(PROMPT.format(platform=platform, streamer=streamer, text=text[:4000]), cfg, usage, 250)
    if not d:
        return None
    try:
        return {"score": int(d.get("score", 0)), "title": str(d.get("title", ""))[:80],
                "reason": str(d.get("reason", ""))[:300], "keep": bool(d.get("keep", True))}
    except (TypeError, ValueError):
        return None
