"""Découpage « intelligent » d'un clip autour d'un ou plusieurs moments forts.

Au lieu de « pic − 40 s / pic + 20 s », on raisonne comme un monteur :
  1. DÉBUT = là où commence l'histoire qui mène au pic : un début de phrase, après une pause,
     là où le sujet change (mots nouveaux), idéalement une question / exclamation (accroche),
     10 à 30 s avant le pic. On ne commence jamais au milieu d'une phrase ni en pleine action.
  2. FIN = quand la réaction est retombée (l'intensité du live repasse sous la moitié du pic)
     ET à la fin d'une phrase — pour garder la chute et la réaction, pas plus.
  3. PLUSIEURS PICS proches → un seul clip ; si c'est trop long, on coupe le « creux » entre eux.
  4. TEMPS MORTS : les silences longs pendant lesquels rien ne se passe sont coupés (jump cut).

Chaque choix est expliqué (liste `reasons`) et affiché dans l'onglet « Pourquoi ? ».
Inspiré des critères publics d'OpusClip (accroche, fluidité, valeur) — sans IA payante.
"""
from __future__ import annotations

import re

from .virality import EMOTION

STOP = {"le", "la", "les", "de", "des", "du", "un", "une", "et", "je", "tu", "il", "elle", "on", "nous", "vous",
        "ils", "est", "c'est", "pas", "que", "qui", "en", "dans", "ce", "ça", "sur", "pour", "mais", "ou", "mon",
        "ma", "ton", "ta", "là", "oui", "non", "a", "à", "y", "j'ai", "the", "a", "to", "and", "of", "i", "you", "it"}


def _norm(w: str) -> str:
    return re.sub(r"[^\w'’-]", "", w.lower()).replace("’", "'")


def sentences(words: list[dict]) -> list[dict]:
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if w["w"].strip()[-1:] in ".?!" or nxt is None or nxt["s"] - w["e"] > 0.8:
            gap_before = cur[0]["s"] - out[-1]["e"] if out else 9.0
            text = " ".join(x["w"] for x in cur)
            out.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": text, "gap": gap_before, "n": len(cur)})
            cur = []
    return out


def _interp(curve: list[tuple[float, float]], t: float) -> float:
    if not curve:
        return 0.0
    if t <= curve[0][0]:
        return curve[0][1]
    for (a, va), (b, vb) in zip(curve, curve[1:]):
        if a <= t <= b:
            return va + (vb - va) * (t - a) / max(b - a, 1e-6)
    return curve[-1][1]


def _content(words: list[dict], a: float, b: float) -> set[str]:
    return {_norm(w["w"]) for w in words if a <= w["s"] < b and len(_norm(w["w"])) > 2 and _norm(w["w"]) not in STOP}


def story_window(words: list[dict], peaks: list[float], curve: list[tuple[float, float]], total: float,
                 min_s: float, max_s: float, threshold: float = 2.0, remove_silences: bool = True) -> dict:
    words = [w for w in words if not w.get("skip")]
    peaks = sorted(p for p in peaks if 0 <= p <= total) or [total / 2]
    p0, p1 = peaks[0], peaks[-1]
    sents = sentences(words)
    peak_level = max([_interp(curve, p) for p in peaks] + [threshold])
    reasons: list[str] = []

    # ---------------------------------------------------------------- 1. début de l'histoire
    lo, hi = max(0.0, p0 - 45), max(0.0, p0 - 3)
    best, best_sc, why = max(0.0, p0 - 20), -1e9, "20 s avant le pic (pas de parole pour se repérer)"
    for s in sents:
        if not lo <= s["s"] <= hi:
            continue
        dist = p0 - s["s"]
        before, after = _content(words, s["s"] - 20, s["s"]), _content(words, s["s"], p0)
        novelty = 1 - (len(before & after) / max(len(after), 1)) if after else 0
        hook = s["text"].strip()[-1:] in "?!" or any(_norm(t) in EMOTION for t in s["text"].split()[:4])
        calm = _interp(curve, s["s"]) / max(peak_level, 1e-6)
        sc = min(s["gap"], 3.0) + 1.5 * novelty + (1.0 if hook else 0) - abs(dist - 18) / 12 - 0.4 * calm
        if sc > best_sc:
            best_sc, best = sc, s["s"]
            bits = []
            if s["gap"] >= 1.2:
                bits.append(f"après une pause de {min(s['gap'], 9):.1f} s")
            if novelty > 0.6:
                bits.append("là où le sujet change")
            if hook:
                bits.append(f"sur une phrase d'accroche (« {s['text'][:50]} »)")
            why = f"{dist:.0f} s avant le pic, au début d'une phrase" + (", " + ", ".join(bits) if bits else "")
    start = max(0.0, best - 0.15)
    reasons.append(f"Début : {why}")

    # ---------------------------------------------------------------- 2. fin = réaction retombée + fin de phrase
    settle, t = None, p1 + 4
    while t <= min(p1 + 35, total):
        if _interp(curve, t) < 0.5 * peak_level:
            settle = t
            break
        t += 1
    settle = settle if settle is not None else min(p1 + 15, total)
    ends = [s["e"] for s in sents if settle - 2 <= s["e"] <= settle + 8]
    end = min(min(ends) + 0.3 if ends else settle + 1.5, total)
    reasons.append(f"Fin : {end - p1:.0f} s après le pic, quand la réaction est retombée"
                   + (" et à la fin d'une phrase" if ends else ""))

    # ---------------------------------------------------------------- 3. durée : min / max, plusieurs pics
    if end - start < min_s:
        earlier = [s["s"] for s in sents if end - max_s <= s["s"] < start]
        start = max(0.0, max([x for x in earlier if end - x >= min_s], default=end - min_s))
        if end - start < min_s:
            end = min(total, start + min_s)
        reasons.append(f"Allongé à {end - start:.0f} s (durée minimale réglée)")
    segs = [[start, end]]
    if len(peaks) > 1:
        reasons.append(f"{len(peaks)} moments forts rapprochés regroupés dans ce clip")
    if end - start > max_s and len(peaks) > 1:
        # on coupe les creux entre deux pics (intensité basse pendant > 8 s)
        cuts = []
        for a, b in zip(peaks, peaks[1:]):
            ca, cb = a + 8, b - 12
            if cb - ca > 4 and max(_interp(curve, x) for x in _frange(ca, cb, 1)) < 0.6 * peak_level:
                # coupe entre deux mots (jump cut) : de la fin d'un mot au début d'un autre
                sa = next((w["e"] for w in words if ca <= w["e"] <= cb), ca)
                sb = max((w["s"] for w in words if sa < w["s"] <= cb), default=cb)
                if sb - sa > 3:
                    cuts.append((sa + 0.2, sb - 0.15))
        for a, b in cuts:
            segs = _cut(segs, a, b)
        if cuts:
            reasons.append(f"{len(cuts)} creux coupé(s) entre les moments forts")
    if _dur(segs) > max_s:  # toujours trop long : on avance le début (jamais la fin, qui porte la chute)
        excess = _dur(segs) - max_s
        later = [s["s"] for s in sents if segs[0][0] + excess <= s["s"] < p0 - 3]
        new0 = min(later) if later else min(segs[0][0] + excess, p0 - 3)
        segs[0][0] = new0
        reasons.append(f"Début avancé pour tenir en {max_s:.0f} s max")

    # ---------------------------------------------------------------- 4. temps morts
    if remove_silences:
        n = 0
        for a, b in zip(words, words[1:]):
            gap_a, gap_b = a["e"] + 0.35, b["s"] - 0.25
            if gap_b - gap_a > 1.2 and all(abs(p - (gap_a + gap_b) / 2) > 4 for p in peaks) \
                    and _interp(curve, (gap_a + gap_b) / 2) < 0.6 * peak_level \
                    and any(s0 < gap_a and gap_b < e0 for s0, e0 in segs):
                segs = _cut(segs, gap_a, gap_b)
                n += 1
        if n:
            reasons.append(f"{n} silence(s) coupé(s) (temps morts)")
    segs = [[round(a, 2), round(b, 2)] for a, b in segs if b - a > 0.4]
    return {"segments": segs, "reasons": reasons, "peaks": [round(p, 2) for p in peaks]}


def _frange(a: float, b: float, step: float):
    x = a
    while x <= b:
        yield x
        x += step


def _dur(segs) -> float:
    return sum(b - a for a, b in segs)


def _cut(segs, a: float, b: float):
    out = []
    for s, e in segs:
        if b <= s or a >= e:
            out.append([s, e])
        else:
            if a > s:
                out.append([s, a])
            if b < e:
                out.append([b, e])
    return out
