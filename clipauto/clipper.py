"""Extraction de la source, transcription mot à mot, découpe intelligente et rendu final 9:16."""
from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np

from .captions import build_ass
from .recorder import Segment

log = logging.getLogger(__name__)
FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"
OUT_W, OUT_H = 1080, 1920


async def run(*args: str) -> bytes:
    p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                             stderr=asyncio.subprocess.PIPE)
    out, err = await p.communicate()
    if p.returncode:
        raise RuntimeError(f"{args[0]} a échoué: {err.decode()[-800:]}")
    return out


async def probe_duration(path: Path) -> float:
    out = await run("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path))
    return float(out.strip() or 0)


async def probe_size(path: Path) -> tuple[int, int]:
    out = await run("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                    "stream=width,height", "-of", "csv=p=0", str(path))
    w, h = out.decode().strip().split(",")[:2]
    return int(w), int(h)


# ---------------------------------------------------------------- source
async def extract_source(segments: list[Segment], t0: float, t1: float, out: Path) -> Path:
    used = [s for s in segments if s.start + s.duration > t0 and s.start < t1]
    if not used:
        raise RuntimeError("aucun segment ne couvre ce moment (buffer trop court ?)")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        lst = Path(td) / "list.txt"
        lst.write_text("".join(f"file '{s.path.resolve()}'\n" for s in used))
        await run("ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                  "-ss", f"{max(t0 - used[0].start, 0):.2f}", "-t", f"{t1 - t0:.2f}",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-g", "30",
                  "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out))
    return out


async def cut_file(src: Path, t0: float, t1: float, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    await run("ffmpeg", "-loglevel", "error", "-y", "-ss", f"{max(t0, 0):.2f}", "-i", str(src),
              "-t", f"{t1 - t0:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-g", "30",
              "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out))
    return out


async def thumbnail(src: Path, t: float, out: Path) -> Path:
    await run("ffmpeg", "-loglevel", "error", "-y", "-ss", f"{max(t, 0):.2f}", "-i", str(src),
              "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(out))
    return out


# ---------------------------------------------------------------- transcription
@lru_cache(maxsize=2)
def _model(size: str):
    from faster_whisper import WhisperModel
    return WhisperModel(size, compute_type="int8")


def load_pcm(path: Path) -> np.ndarray:
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "pipe:1"], capture_output=True, check=True).stdout
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768


def transcribe(path: Path, model_size: str = "small", language: str | None = None) -> list[dict]:
    """Mots avec horodatage précis (faster-whisper word_timestamps + VAD)."""
    audio = load_pcm(path)
    segs, _ = _model(model_size).transcribe(audio, word_timestamps=True, vad_filter=True,
                                            language=language or None, beam_size=5,
                                            condition_on_previous_text=False)
    words = []
    for s in segs:
        for w in s.words or []:
            if w.word.strip():
                words.append({"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3)})
    # « qu » + « 'il » → « qu'il » ; « peut » + « -être » → « peut-être »
    merged: list[dict] = []
    for w in words:
        if merged and (w["w"][:1] in "'’-" or merged[-1]["w"][-1:] in "'’"):
            merged[-1] = {"w": merged[-1]["w"] + w["w"], "s": merged[-1]["s"], "e": w["e"]}
        else:
            merged.append(w)
    words = merged
    # évite les chevauchements / mots de durée nulle (synchro propre à l'écran)
    for i, w in enumerate(words):
        if w["e"] - w["s"] < 0.08:
            w["e"] = w["s"] + 0.08
        if i + 1 < len(words) and w["e"] > words[i + 1]["s"]:
            w["e"] = max(words[i + 1]["s"], w["s"] + 0.05)
    return words


# ---------------------------------------------------------------- découpe intelligente
def smart_trim(words: list[dict], peak: float, total: float, min_s: float, max_s: float,
               pre: float, post: float, snap: bool = True) -> tuple[float, float]:
    """Choisit [début, fin] autour du pic : durée dans [min_s, max_s], coupe sur des pauses
    entre phrases (jamais au milieu d'un mot)."""
    want = min(max(pre + post, min_s), max_s)
    start = max(0.0, peak - pre * want / (pre + post))
    end = min(total, start + want)
    start = max(0.0, end - want)
    if not snap or not words:
        return round(start, 2), round(end, 2)

    # frontières possibles = pauses entre deux mots (plus la pause est longue, mieux c'est)
    bounds = [(0.0, 9.0)] + [((a["e"] + b["s"]) / 2, b["s"] - a["e"] + (0.6 if a["w"][-1:] in ".?!" else 0))
                             for a, b in zip(words, words[1:])] + [(total, 9.0)]

    def best(target, lo, hi):
        cands = [(abs(t - target) - 2.0 * g, t) for t, g in bounds if lo <= t <= hi]
        return min(cands)[1] if cands else min(max(target, lo), hi)

    s = best(start, max(0, start - 4), min(start + 4, peak - 2))
    e = best(s + want, s + min_s, min(s + max_s, total))
    return round(s, 2), round(e, 2)


# ---------------------------------------------------------------- rendu 9:16
def _crop(rect: dict, iw: int, ih: int, aspect: float) -> str:
    """crop ffmpeg d'un rectangle (fractions 0-1) agrandi/réduit pour avoir le bon ratio, centré."""
    x, y, w, h = rect.get("x", 0), rect.get("y", 0), rect.get("w", 1), rect.get("h", 1)
    pw, ph = w * iw, h * ih
    if pw / ph > aspect:
        nw, nh = ph * aspect, ph
    else:
        nw, nh = pw, pw / aspect
    cx, cy = x * iw + pw / 2, y * ih + ph / 2
    nx = min(max(cx - nw / 2, 0), iw - nw)
    ny = min(max(cy - nh / 2, 0), ih - nh)
    return f"crop={int(nw) // 2 * 2}:{int(nh) // 2 * 2}:{int(nx)}:{int(ny)}"


def layout_filter(layout: dict, iw: int, ih: int) -> str:
    mode = layout.get("mode", "blur")
    if mode == "fill":
        fx = float(layout.get("focus", {}).get("x", 0.5))
        nw = ih * 9 / 16
        x = min(max(fx * iw - nw / 2, 0), iw - nw)
        return f"[0:v]crop={int(nw) // 2 * 2}:{ih}:{int(x)}:0,scale={OUT_W}:{OUT_H},setsar=1[v]"
    if mode == "split":
        r = float(layout.get("split_ratio", 0.42))
        th = int(OUT_H * r) // 2 * 2
        bh = OUT_H - th
        top = _crop(layout.get("facecam", {}), iw, ih, OUT_W / th)
        bot = _crop(layout.get("gameplay", {}), iw, ih, OUT_W / bh)
        return (f"[0:v]split[a][b];[a]{top},scale={OUT_W}:{th}[t];[b]{bot},scale={OUT_W}:{bh}[g];"
                f"[t][g]vstack,setsar=1[v]")
    if mode == "fit":
        return (f"[0:v]scale={OUT_W}:-2,pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[v]")
    # blur : vidéo entière au centre + fond flouté
    zoom = float(layout.get("zoom", 1.0))
    return (f"[0:v]split[a][b];[a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{OUT_H},boxblur=30:3,eq=brightness=-0.08[bg];"
            f"[b]scale={int(OUT_W * zoom) // 2 * 2}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")


async def render(source: Path, words: list[dict], edit: dict, out: Path) -> Path:
    t0, t1 = edit["trim"]
    iw, ih = await probe_size(source)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        ass = Path(td) / "subs.ass"
        kept = [w for w in words if w["e"] > t0 and w["s"] < t1]
        ass.write_text(build_ass(kept if edit.get("captions", True) else [], edit["style"], offset=t0,
                                 duration=t1 - t0, hook=edit.get("hook"), hook_text=edit.get("title", "")),
                       encoding="utf-8")
        fc = layout_filter(edit.get("layout", {}), iw, ih) + f";[v]ass={ass}:fontsdir={FONTS_DIR}[out]"
        speed = float(edit.get("speed", 1.0))
        af = ["-af", f"atempo={speed}"] if abs(speed - 1) > 1e-3 else []
        if abs(speed - 1) > 1e-3:
            fc = fc.replace("[out]", f",setpts=PTS/{speed}[out]")
        await run("ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}",
                  "-i", str(source), "-filter_complex", fc, "-map", "[out]", "-map", "0:a?", *af,
                  "-c:v", "libx264", "-preset", "faster", "-crf", "20", "-pix_fmt", "yuv420p",
                  "-r", "30", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out))
    log.info("rendu: %s", out)
    return out
