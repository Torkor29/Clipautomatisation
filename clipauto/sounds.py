"""Recherche de sons libres via Openverse (Freesound, Wikimedia, Jamendo…), sans clé API.

On ne garde que les licences utilisables commercialement : CC0 (aucune obligation) et CC BY
(créditer l'auteur). Chaque son importé est noté dans assets/CREDITS.json avec son auteur et
sa licence, pour pouvoir créditer si besoin.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import aiohttp

API = "https://api.openverse.org/v1/audio/"
UA = {"User-Agent": "ClipAuto/1.0 (open source clipping tool)"}


async def search(q: str, kind: str = "sfx", page: int = 1) -> list[dict]:
    params = {"q": q, "license": "cc0,by", "page_size": "20", "page": str(page)}
    async with aiohttp.ClientSession(headers=UA, timeout=aiohttp.ClientTimeout(total=20)) as s:
        for p in (params, {k: v for k, v in params.items() if k != "license"}):  # l'API renvoie parfois 500 sur les filtres
            async with s.get(API, params=p) as r:
                if r.status == 200:
                    data = await r.json()
                    break
        else:
            raise RuntimeError("Openverse ne répond pas, réessaie dans un instant")
    out = []
    for r in data.get("results", []):
        lic = (r.get("license") or "").lower()
        if lic not in ("cc0", "by", "pdm"):
            continue
        dur = (r.get("duration") or 0) / 1000
        if kind == "sfx" and dur and dur > 20:
            continue
        if kind == "music" and dur and dur < 20:
            continue
        if not str(r.get("url", "")).startswith("https://"):
            continue
        out.append({"id": r["id"], "title": r.get("title") or "son", "url": r["url"], "duration": dur,
                    "license": lic, "creator": r.get("creator") or "", "source": r.get("source"),
                    "page": r.get("foreign_landing_url")})
    return out


async def download(item: dict, assets: Path) -> str:
    base = re.sub(r"[^\w\-]+", "_", Path(item.get("title") or "son").stem)[:40].strip("_") or "son"
    ext = Path(item["url"].split("?")[0]).suffix.lower()
    ext = ext if ext in (".mp3", ".ogg", ".wav", ".m4a", ".flac") else ".mp3"
    dst = assets / f"{base}{ext}"
    i = 1
    while dst.exists():
        dst = assets / f"{base}_{i}{ext}"
        i += 1
    async with aiohttp.ClientSession(headers=UA, timeout=aiohttp.ClientTimeout(total=60)) as s:
        async with s.get(item["url"]) as r:
            r.raise_for_status()
            data = await r.read()
    if len(data) > 30 * 1024 * 1024:
        raise RuntimeError("fichier trop gros")
    dst.write_bytes(data)
    credits = assets / "CREDITS.json"
    c = json.loads(credits.read_text()) if credits.exists() else {}
    c[dst.name] = {k: item.get(k) for k in ("title", "creator", "license", "source", "page")}
    credits.write_text(json.dumps(c, ensure_ascii=False, indent=1))
    return dst.name
