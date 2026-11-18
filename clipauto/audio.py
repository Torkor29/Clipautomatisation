"""Signal audio : volume (dB RMS) par demi-seconde, extrait de chaque segment enregistré."""
from __future__ import annotations

import asyncio

import numpy as np

SR, HOP = 16000, 0.5


async def segment_loudness(path: str, start: float) -> list[tuple[float, float]]:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-loglevel", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SR),
        "-f", "s16le", "pipe:1", stdout=asyncio.subprocess.PIPE)
    raw, _ = await proc.communicate()
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    n = int(SR * HOP)
    out = []
    for i in range(len(x) // n):
        rms = float(np.sqrt(np.mean(x[i * n:(i + 1) * n] ** 2)) + 1e-9)
        out.append((start + i * HOP, 20 * np.log10(rms)))
    return out
