"""« Monteur IA » optionnel : une IA texte lit la transcription horodatée + l'intensité du live +
quelques messages du chat, et décide où commencer / finir le clip, quoi couper, le titre et le score.

Fonctionne avec toute API compatible OpenAI (même format partout) :
  deepseek   → api.deepseek.com   (payant mais quasi gratuit : ~0,0003 $ par clip)
  openrouter → openrouter.ai      (modèles « :free » gratuits, limités en nombre d'appels / jour)
  groq       → api.groq.com       (palier gratuit, très rapide)
  gemini     → API Gemini (palier gratuit sur un projet sans facturation)
  ollama     → sur ton serveur (gratuit, mais il faut beaucoup de RAM)
Clés lues dans l'environnement (.env) : DEEPSEEK_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY, GEMINI_API_KEY.
Toujours plafonné (appels / jour) et jamais bloquant : en cas d'erreur, on garde le découpage local.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request

log = logging.getLogger(__name__)

PROVIDERS = {
    "deepseek": {"url": "https://api.deepseek.com/v1", "key": "DEEPSEEK_API_KEY", "model": "deepseek-chat",
                 "label": "DeepSeek (≈ 0,0003 $ / clip)"},
    "openrouter": {"url": "https://openrouter.ai/api/v1", "key": "OPENROUTER_API_KEY", "model": "openrouter/free",
                   "label": "OpenRouter (modèles gratuits)"},
    "groq": {"url": "https://api.groq.com/openai/v1", "key": "GROQ_API_KEY", "model": "llama-3.3-70b-versatile",
             "label": "Groq (palier gratuit)"},
    "gemini": {"url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": "GEMINI_API_KEY",
               "model": "gemini-2.5-flash-lite", "label": "Gemini (palier gratuit)"},
    "vertex": {"url": "https://aiplatform.googleapis.com/v1", "key": "VERTEX_API_KEY", "model": "gemini-2.5-flash",
               "label": "Gemini via Vertex AI (crédits Google Cloud)"},
    "ollama": {"url": "http://localhost:11434/v1", "key": None, "model": "qwen2.5:7b", "label": "Ollama (local)"},
}


def _vertex(prompt: str, cfg: dict, max_tokens: int) -> str:
    """Vertex AI (utilise les crédits de l'essai Google Cloud). Clé API autorisée pour « Vertex AI API »."""
    model = cfg.get("model") or PROVIDERS["vertex"]["model"]
    proj = os.environ.get("VERTEX_PROJECT")
    path = (f"projects/{proj}/locations/global/publishers/google/models/{model}" if proj
            else f"publishers/google/models/{model}")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": "Tu es monteur vidéo expert TikTok/Shorts. Tu réponds UNIQUEMENT en JSON valide."}]},
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens, "responseMimeType": "application/json"}}
    req = urllib.request.Request(f"https://aiplatform.googleapis.com/v1/{path}:generateContent?key={os.environ['VERTEX_API_KEY']}",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    out = json.loads(urllib.request.urlopen(req, timeout=90).read())
    return "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])


def available(cfg: dict) -> bool:
    p = PROVIDERS.get(cfg.get("provider") or "")
    return bool(cfg.get("enabled") and p and (p["key"] is None or os.environ.get(p["key"])))


def _budget(cfg: dict, usage: dict) -> bool:
    day = time.strftime("%Y-%m-%d")
    if usage.get("day") != day:
        usage.clear()
        usage.update(day=day, calls=0)
    return usage["calls"] < int(cfg.get("max_calls_per_day", 50))


def call_json(prompt: str, cfg: dict, usage: dict, max_tokens: int = 600) -> dict | None:
    if not available(cfg) or not _budget(cfg, usage):
        return None
    p = PROVIDERS[cfg["provider"]]
    if cfg["provider"] == "vertex":
        try:
            txt = _vertex(prompt, cfg, max_tokens)
            usage["calls"] += 1
            m = re.search(r"\{.*\}", txt, re.S)
            return json.loads(m.group(0) if m else txt)
        except Exception as e:
            log.warning("IA (vertex) indisponible : %s", e)
            return None
    base = (cfg.get("ollama_url", "http://localhost:11434") + "/v1") if cfg["provider"] == "ollama" else p["url"]
    body = {"model": cfg.get("model") or p["model"], "temperature": 0.2, "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": "Tu es monteur vidéo expert TikTok/Shorts. Tu réponds UNIQUEMENT en JSON valide."},
                         {"role": "user", "content": prompt}]}
    headers = {"Content-Type": "application/json"}
    if p["key"]:
        headers["Authorization"] = f"Bearer {os.environ[p['key']]}"
    try:
        req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
        out = json.loads(urllib.request.urlopen(req, timeout=90).read())
        usage["calls"] += 1
        txt = out["choices"][0]["message"]["content"] or ""
        m = re.search(r"\{.*\}", txt, re.S)
        return json.loads(m.group(0) if m else txt)
    except Exception as e:  # jamais bloquant
        log.warning("IA (%s) indisponible : %s", cfg.get("provider"), e)
        return None


EDIT_PROMPT = """Extrait d'un live {platform} de {streamer}{game}. Les moments forts détectés (chat qui s'emballe) sont à {peaks} s.
Transcription horodatée (secondes depuis le début de l'extrait ; intensité du live 0-10 entre crochets) :
{lines}
Messages du chat au moment fort : {chat}

Choisis le meilleur clip TikTok/Shorts ({min_s}-{max_s} s) qui contient le(s) moment(s) fort(s) :
- "start" : début d'une phrase qui MET EN PLACE la situation (contexte compréhensible sans avoir vu le live, accroche dès la 1re seconde) ;
- "end" : juste après la chute / la réaction, à la fin d'une phrase ;
- "remove" : passages inutiles À L'INTÉRIEUR du clip à couper (digressions, blancs), liste de [début, fin] ;
- "title" : titre accrocheur en français, < 60 caractères, fidèle à ce qui se passe (pas de faux drame) ;
- "score" : potentiel viral 0-100 ; "reason" : une phrase qui explique ton choix ; "keep" : false si le moment ne vaut rien.
JSON : {{"start": nombre, "end": nombre, "remove": [[a, b]], "title": "...", "score": 0, "reason": "...", "keep": true}}"""


def monteur(words: list[dict], peaks: list[float], curve: list[tuple[float, float]], chat: list[dict], total: float,
            min_s: float, max_s: float, streamer: str, platform: str, game: str | None, cfg: dict, usage: dict) -> dict | None:
    from .story import _interp, sentences
    sents = sentences([w for w in words if not w.get("skip")])
    if not sents:
        return None
    lines = "\n".join(f"[{s['s']:.1f}-{s['e']:.1f}] [{_interp(curve, (s['s'] + s['e']) / 2):.1f}] {s['text']}" for s in sents)[:9000]
    chat_s = " | ".join(f"{m['m'][:60]}" for m in (chat or [])[:20]) or "(aucun)"
    prompt = EDIT_PROMPT.format(platform=platform, streamer=streamer or "un streamer", game=f" (jeu : {game})" if game else "",
                                peaks=", ".join(f"{p:.0f}" for p in peaks), lines=lines, chat=chat_s,
                                min_s=int(min_s), max_s=int(max_s))
    d = call_json(prompt, cfg, usage)
    if not d:
        return None
    try:
        start, end = float(d["start"]), float(d["end"])
    except (KeyError, TypeError, ValueError):
        return None
    # garde-fous : bornes, phrases entières, durée, le pic doit rester dans le clip
    starts, ends = [s["s"] for s in sents], [s["e"] for s in sents]
    start = min(starts, key=lambda x: abs(x - start))
    end = min(ends, key=lambda x: abs(x - end)) + 0.3
    p0, p1 = min(peaks), max(peaks)
    if not (start < p0 and end > p1 and 0 <= start < end <= total + 0.5):
        log.info("IA : bornes refusées (%.1f-%.1f, pics %s)", start, end, peaks)
        return {"title": str(d.get("title", ""))[:80], "score": int(d.get("score", 0) or 0),
                "reason": str(d.get("reason", ""))[:300], "keep": bool(d.get("keep", True)), "segments": None}
    segs = [[max(start - 0.15, 0), min(end, total)]]
    for r in d.get("remove") or []:
        try:
            a, b = float(r[0]), float(r[1])
        except (TypeError, ValueError, IndexError):
            continue
        if start < a < b < end and not any(a - 2 < p < b + 2 for p in peaks):
            from .story import _cut
            trial = _cut(segs, a, b)
            if sum(y - x for x, y in trial) >= min_s * 0.9:  # on ne coupe pas au point de rendre le clip trop court
                segs = trial
    dur = sum(b - a for a, b in segs)
    if dur < min_s * 0.8 or dur > max_s * 1.25:
        segs = None
    return {"segments": [[round(a, 2), round(b, 2)] for a, b in segs] if segs else None,
            "title": str(d.get("title", ""))[:80], "score": max(0, min(100, int(d.get("score", 0) or 0))),
            "reason": str(d.get("reason", ""))[:300], "keep": bool(d.get("keep", True))}
