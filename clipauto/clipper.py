"""Étape 4 : découper [pic - pre_roll, pic + post_roll], format 9:16, sous-titres."""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from .recorder import Segment

log = logging.getLogger(__name__)

# 9:16 1080x1920 : vidéo nette au centre, même vidéo floutée en fond (standard TikTok/Shorts)
VERTICAL = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:2[bg];"
            "[0:v]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")


async def _run(*args: str) -> None:
    p = await asyncio.create_subprocess_exec(*args, stderr=asyncio.subprocess.PIPE)
    _, err = await p.communicate()
    if p.returncode:
        raise RuntimeError(f"{args[0]} a échoué: {err.decode()[-500:]}")


def _srt_time(t: float) -> str:
    h, r = divmod(max(t, 0), 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02}:{int(m):02}:{int(s):02},{int((s % 1) * 1000):03}"


def transcribe_srt(video: Path, srt: Path, model_size: str = "small", language: str | None = None) -> str:
    """Sous-titres mot à mot regroupés par 3 mots (style TikTok). Renvoie le texte complet."""
    from faster_whisper import WhisperModel
    import numpy as np
    import subprocess

    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "pipe:1"], capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
    model = WhisperModel(model_size, compute_type="int8")
    segs, _ = model.transcribe(audio, word_timestamps=True, vad_filter=True, language=language)
    words = [w for s in segs for w in (s.words or [])]
    lines, full = [], []
    for i in range(0, len(words), 3):
        g = words[i:i + 3]
        txt = "".join(w.word for w in g).strip()
        full.append(txt)
        lines.append(f"{len(lines) + 1}\n{_srt_time(g[0].start)} --> {_srt_time(g[-1].end)}\n{txt.upper()}\n")
    srt.write_text("\n".join(lines))
    return " ".join(full)


async def make_clip(segments: list[Segment], t_peak: float, out: Path, pre: float = 40,
                    post: float = 20, vertical: bool = True, captions: bool = True,
                    whisper_model: str = "small", language: str | None = None) -> dict:
    t0, t1 = t_peak - pre, t_peak + post
    used = [s for s in segments if s.start + s.duration > t0 and s.start < t1]
    if not used:
        raise RuntimeError("aucun segment ne couvre ce moment (buffer trop court ?)")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        lst = Path(td) / "list.txt"
        lst.write_text("".join(f"file '{s.path.resolve()}'\n" for s in used))
        offset = max(t0 - used[0].start, 0)
        raw = Path(td) / "raw.mp4"
        await _run("ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                   "-ss", f"{offset:.2f}", "-t", f"{t1 - t0:.2f}", "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "20", "-c:a", "aac", "-b:a", "160k", str(raw))
        text = ""
        vf = VERTICAL if vertical else "null"
        if captions:
            srt = Path(td) / "subs.srt"
            text = await asyncio.to_thread(transcribe_srt, raw, srt, whisper_model, language)
            if srt.read_text().strip():
                style = ("FontName=DejaVu Sans,Bold=1,FontSize=16,PrimaryColour=&H00FFFFFF,"
                         "OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=0,Alignment=2,MarginV=70")
                vf += f",subtitles={srt}:force_style='{style}'"
        await _run("ffmpeg", "-loglevel", "error", "-y", "-i", str(raw), "-filter_complex", vf,
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "copy",
                   "-movflags", "+faststart", str(out))
    log.info("clip prêt: %s", out)
    return {"path": str(out), "transcript": text, "start": t0, "end": t1}
