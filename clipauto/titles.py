"""Titres d'accroche sans IA : plusieurs propositions, la meilleure est choisie, les autres
sont proposées dans l'éditeur.

Deux familles :
  1. une CITATION courte et forte du streamer (phrase entière, 3-8 mots, avec de l'émotion),
     jamais un bout de phrase coupé ;
  2. un MODÈLE construit à partir de ce qui s'est passé (le chat a explosé de rire, gros pic de
     son, mots-clés, jeu en cours…).
"""
from __future__ import annotations

import re

from .virality import EMOTION

LAUGH = ["{S} n'en peut plus 😂", "Le chat est MORT de rire 💀", "Personne n'était prêt pour ça 😭",
         "{S} a fait rire tout le live 😂"]
HYPE = ["Le chat a EXPLOSÉ 🔥", "Le moment où tout a basculé 😳", "{S} a choqué tout le monde 😱",
        "Le chat n'en revenait pas 🤯"]
SHOUT = ["{S} a complètement craqué 😱", "Ça a dégénéré d'un coup 💥", "{S} ne s'y attendait PAS 😳"]
CALM = ["{S} raconte ça… 👀", "Écoute bien la fin 👀", "Attends la fin 😭"]
TOPIC = {
    "police": "{S} vs la police 🚓", "flic": "{S} vs la police 🚓", "braquage": "Le braquage tourne mal 💰",
    "argent": "{S} et l'argent 💸", "million": "Des millions en jeu 💸", "mort": "{S} n'a pas survécu 💀",
    "tué": "{S} n'a pas survécu 💀", "perdu": "{S} a tout perdu 😭", "gagné": "{S} a GAGNÉ 🏆",
    "voiture": "{S} au volant, mauvaise idée 🚗", "chien": "Le chien a tout volé 🐶",
}


BAD_END = {"je", "j'ai", "tu", "il", "elle", "on", "le", "la", "les", "de", "des", "du", "un", "une", "et", "que",
           "qui", "mais", "pour", "en", "a", "à", "dans", "sur", "avec", "ce", "ça", "mon", "ma", "ton", "the", "a",
           "to", "and", "of", "i", "you"}


def _clean_sentence(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" ,;:-")
    s = re.sub(r"^(euh|bah|ben|alors|donc|et|mais|genre)\s+", "", s, flags=re.I)
    return s[:1].upper() + s[1:] if s else s


def _nbsp(s: str) -> str:
    return re.sub(r"\s+([!?:;»])", " \\1", re.sub(r"«\s+", "« ", s))


def quotes(words: list[dict]) -> list[tuple[float, str]]:
    text = " ".join(w["w"] for w in words if not w.get("skip"))
    out = []
    for s in re.split(r"(?<=[.!?…])\s+", text):
        s = _clean_sentence(s)
        toks = [re.sub(r"[^\w'’-]", "", t.lower()) for t in s.split()]
        if not 4 <= len(toks) <= 8 or not s[-1:] in ".!?" or toks[-1] in BAD_END or "'" in s.replace("’", "'").split()[-1][:1]:
            continue  # uniquement des phrases ENTIÈRES, courtes, qui ne finissent pas en suspens
        emo = sum(t in EMOTION for t in toks)
        score = 2.5 * s.count("!") + 1.5 * s.count("?") + 1.5 * emo - 0.3 * abs(len(toks) - 5)
        if emo == 0 and "!" not in s and "?" not in s:
            score -= 3  # une phrase plate fait un mauvais titre
        out.append((score, f"« {s.rstrip('.')} »"))
    return sorted(out, reverse=True)


METHOD = re.compile(r"\b(?:la|ma|une|cette)\s+(m[ée]thode|technique|formule|astuce|r[èe]gle|strat[ée]gie|recette)\s+"
                    r"(du|de la|des|de l'|d'|de)\s*([\w'’-]+(?:\s+[\w'’-]+)?)", re.I)


def own_hook(words: list[dict]) -> list[tuple[float, str]]:
    """La question / phrase d'accroche dite au DÉBUT : c'est souvent le meilleur titre (le créateur l'a écrite pour ça)."""
    kept = [w for w in words if not w.get("skip")]
    if not kept:
        return []
    t0 = kept[0]["s"]
    text = " ".join(w["w"] for w in kept if w["s"] < t0 + 12)
    out = []
    for i, s in enumerate(re.split(r"(?<=[.!?])\s+", text)[:3]):
        s = _clean_sentence(s)
        n = len(s.split())
        if s.endswith("?") and 4 <= n <= 16:
            out.append((9 - i, s))
        elif s.endswith("!") and 3 <= n <= 10:
            out.append((6 - i, s))
    return out


def topic(words: list[dict]) -> list[tuple[float, str]]:
    text = " ".join(w["w"] for w in words if not w.get("skip"))
    out = []
    m = METHOD.search(text)
    if m:
        name = f"{m.group(1).lower()} {m.group(2).lower()} {m.group(3).strip()}".replace("d' ", "d'").replace("de l' ", "de l'")
        name = re.sub(r"\s+", " ", name)
        out.append((7, f"La {name} 🎯"))
        out.append((5, f"La {name}, expliquée en 1 minute"))
    return out


def suggest(words: list[dict], streamer: str, detail: dict, game: str | None = None) -> list[str]:
    S = (streamer[:1].upper() + streamer[1:]) if streamer else "Il"
    z = detail.get("z") or {}
    live = any(k in z for k in ("chat_rate", "unique_chatters", "laugh_emotes", "hype_emotes"))  # vrai live (chat)
    cands: list[tuple[float, str]] = own_hook(words) + topic(words)
    for sc, q in quotes(words)[:3]:
        cands.append((sc + 2, q + (" 😂" if z.get("laugh_emotes", 0) > 2 else " 😳")))
    toks = {re.sub(r"[^\w'’-]", "", w["w"].lower()) for w in words if not w.get("skip")}
    for k, tpl in TOPIC.items():
        if k in toks:
            cands.append((4.5, tpl))
    if z.get("laugh_emotes", 0) >= 1.5:
        cands += [(4 + z["laugh_emotes"] / 3 - i * .4, t) for i, t in enumerate(LAUGH)]
    if max(z.get("chat_rate", 0), z.get("unique_chatters", 0), z.get("hype_emotes", 0)) >= 1.5:
        cands += [(3.5 - i * .4, t) for i, t in enumerate(HYPE)]
    emo = sum(t in EMOTION for t in toks)
    if (live and z.get("audio", 0) >= 1.5) or (z.get("audio", 0) >= 3 and emo >= 3):
        cands += [(3.2 - i * .4, t) for i, t in enumerate(SHOUT)]
    if game:
        g = re.sub(r"Grand Theft Auto", "GTA", game).replace(" V", " 5").strip()
        cands.append((2.5, f"{S} sur {g}… 😳"))
    if live:
        cands += [(1 - i * .3, t) for i, t in enumerate(CALM)]
    seen, out = set(), []
    for _, t in sorted(cands, key=lambda x: -x[0]):
        t = _nbsp(t.replace("{S}", S))
        if t.lower() not in seen and len(t) <= 100:
            seen.add(t.lower())
            out.append(t)
    return out[:8]
