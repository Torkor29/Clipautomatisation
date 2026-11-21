"""Lives terminés (VOD Twitch) : liste des derniers lives + analyse complète après coup.

Signaux utilisés pour trouver les moments forts d'une VOD :
  - le CHAT, s'il a été enregistré par ClipAuto pendant le live (fichiers data/chatlogs/*.jsonl) —
    Twitch ne fournit pas le chat des VOD via son API officielle ;
  - le SON de toute la VOD (piste audio seule, la plus légère : ~100 Mo / heure).
Ensuite seuls les passages retenus sont téléchargés en vidéo (pas la VOD entière).
"""
from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

import aiohttp
import numpy as np

from .detector import Detector, Lexicon

log = logging.getLogger(__name__)
_cache: dict[str, tuple[float, list]] = {}


def parse_dur(d: str) -> int:
    h = re.search(r"(\d+)h", d or "")
    m = re.search(r"(\d+)m", d or "")
    s = re.search(r"(\d+)s", d or "")
    return sum(int(x.group(1)) * k for x, k in ((h, 3600), (m, 60), (s, 1)) if x)


async def twitch_vods(twitch, login: str, n: int = 2) -> list[dict]:
    key = f"tw:{login}:{n}"
    if key in _cache and time.time() - _cache[key][0] < 300:
        return _cache[key][1]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
        tok = await twitch._auth(s)
        h = {"Client-Id": twitch.client_id, "Authorization": f"Bearer {tok}"}
        async with s.get("https://api.twitch.tv/helix/users", params={"login": login}, headers=h) as r:
            users = (await r.json()).get("data") or []
        if not users:
            return []
        async with s.get("https://api.twitch.tv/helix/videos",
                         params={"user_id": users[0]["id"], "type": "archive", "first": n}, headers=h) as r:
            vids = (await r.json()).get("data") or []
    out = []
    for v in vids:
        start = datetime.fromisoformat(v["created_at"].replace("Z", "+00:00")).timestamp()
        out.append({"id": v["id"], "title": v["title"], "url": v["url"], "start": start,
                    "duration": parse_dur(v["duration"]), "views": v.get("view_count"),
                    "thumb": (v.get("thumbnail_url") or "").replace("%{width}", "480").replace("%{height}", "270")})
    _cache[key] = (time.time(), out)
    return out


def chat_for(data: Path, platform: str, channel: str, t0: float, t1: float) -> list[tuple[float, str, str]]:
    """Messages enregistrés pendant le live, entre t0 et t1 (heure réelle)."""
    msgs = []
    for f in sorted(glob.glob(str(data / "chatlogs" / f"{platform}_{channel.lower()}_*.jsonl"))):
        try:
            started = int(Path(f).stem.rsplit("_", 1)[1])
        except ValueError:
            continue
        if started > t1 + 60:
            continue
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                try:
                    t, u, m = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if t0 <= t <= t1:
                    msgs.append((t, u, m))
    return sorted(msgs)


async def run(*args: str) -> None:
    p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await p.communicate()
    if p.returncode:
        raise RuntimeError(f"{args[0]} : {err.decode()[-400:]}")


async def download_audio(url: str, out: Path, limit: int | None = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["yt-dlp", "-q", "--no-warnings", "-f", "Audio_Only/bestaudio/worst", "-o", str(out.with_suffix(".%(ext)s"))]
    if limit:
        args += ["--download-sections", f"*0-{limit}"]
    await run(*args, url)
    return next(p for p in out.parent.glob(out.stem + ".*") if p.suffix != ".part")


def loudness(path: Path, hop: float = 0.5) -> list[tuple[float, float]]:
    """Volume (dB) par demi-seconde, en lisant le fichier en flux (peu de RAM même pour 8 h)."""
    sr = 8000
    n = int(sr * hop)
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
                          "-f", "s16le", "pipe:1"], stdout=subprocess.PIPE)
    out, i = [], 0
    while True:
        buf = p.stdout.read(n * 2)
        if len(buf) < n * 2:
            break
        x = np.frombuffer(buf, np.int16).astype(np.float32) / 32768
        out.append((i * hop, float(20 * np.log10(np.sqrt(np.mean(x * x)) + 1e-9))))
        i += 1
    p.wait()
    return out


def find_moments(audio: list[tuple[float, float]], chat: list[tuple[float, str, str]], duration: float,
                 n: int, settings: dict, reaction: float) -> tuple[list[dict], list[tuple[float, float]]]:
    """Rejoue la détection du live sur toute la VOD. Renvoie les N meilleurs moments + la courbe d'intensité."""
    d = settings["detect"]
    weights = dict(d["weights"]) if chat else {"audio": 1.0}
    det = Detector(window=d["window_seconds"], baseline_s=d["baseline_minutes"] * 60, threshold=0, cooldown=0,
                   warmup=0, min_signals=1, weights=weights,
                   lexicon=Lexicon(d["laugh_words"], d["hype_words"], d["keywords"]))
    ai = ci = 0
    series: list[tuple[float, float, dict]] = []
    w = det.window
    now = float(w)
    while now <= duration + reaction:
        while ci < len(chat) and chat[ci][0] < now:
            det.add_message(*chat[ci])
            ci += 1
        while ai < len(audio) and audio[ai][0] < now - reaction:
            det.add_audio(*audio[ai])
            ai += 1
        det.step(now, reaction)
        t, sc, z = det.timeline[-1]
        series.append((t - reaction, sc, z))
        now += w
    curve = [(t, sc) for t, sc, _ in series]
    # meilleurs pics, espacés d'au moins 90 s ; les pics à moins de 60 s du retenu le rejoignent
    order = sorted(range(len(series)), key=lambda i: -series[i][1])
    picks: list[dict] = []
    for i in order:
        t, sc, z = series[i]
        if sc <= 0 or t < 30:
            continue
        if any(abs(t - p["t"]) < 90 for p in picks):
            continue
        near = [series[j][0] for j in range(len(series))
                if abs(series[j][0] - t) < 60 and series[j][1] >= 0.75 * sc]
        picks.append({"t": t, "score": round(sc, 2), "z": z, "peaks": sorted(set([t] + near))})
        if len(picks) >= n:
            break
    return sorted(picks, key=lambda p: p["t"]), curve


async def download_section(url: str, a: float, b: float, out: Path) -> Path:
    """Télécharge uniquement [a, b] : adresse du flux via yt-dlp, puis coupe précise avec ffmpeg."""
    out.parent.mkdir(parents=True, exist_ok=True)
    p = await asyncio.create_subprocess_exec(
        "yt-dlp", "-g", "--no-warnings", "-f", "720p60/720p30/720p/480p30/480p/best[height<=720]/best", url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    o, err = await p.communicate()
    links = [x for x in o.decode().split() if x.startswith("http")]
    if p.returncode or not links:
        raise RuntimeError(f"yt-dlp : {err.decode()[-300:]}")
    a = max(a, 0)
    inputs = []
    for ln in links[:2]:
        inputs += ["-ss", f"{a:.2f}", "-i", ln]
    maps = ["-map", "0:v:0?", "-map", f"{len(links[:2]) - 1}:a:0?"]
    await run("ffmpeg", "-loglevel", "error", "-y", *inputs, "-t", f"{b - a:.2f}", *maps,
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-g", "30", "-c:a", "aac", "-b:a", "160k",
              "-movflags", "+faststart", str(out))
    return out
