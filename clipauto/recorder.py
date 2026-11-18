"""Étape 2 : enregistrer le live avec Streamlink en petits segments horodatés.

On garde une fenêtre glissante (ex. 15 min) sur disque : un clip peut ainsi être
extrait à tout moment, y compris les 40 s qui précèdent le moment fort.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Streamer

log = logging.getLogger(__name__)


@dataclass
class Segment:
    path: Path
    start: float  # horloge murale (epoch) du début du segment
    duration: float


class Recorder:
    def __init__(self, streamer: Streamer, out_dir: Path, quality: str = "best",
                 segment_seconds: int = 10, buffer_minutes: int = 15):
        self.streamer, self.quality = streamer, quality
        self.seg_s, self.buffer_s = segment_seconds, buffer_minutes * 60
        self.dir = out_dir / streamer.platform / streamer.channel.lower() / time.strftime("%Y%m%d-%H%M%S")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.t0: float | None = None
        self._procs: list[asyncio.subprocess.Process] = []

    async def start(self) -> None:
        sl = await asyncio.create_subprocess_exec(
            "streamlink", "--stdout", "--twitch-disable-ads", self.streamer.url, self.quality,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        ff = await asyncio.create_subprocess_exec(
            "ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-map", "0:v:0?", "-map", "0:a:0?",
            "-c", "copy", "-f", "segment", "-segment_time", str(self.seg_s),
            "-reset_timestamps", "1", "-segment_list", str(self.dir / "list.csv"),
            "-segment_list_type", "csv", str(self.dir / "seg_%06d.ts"),
            stdin=asyncio.subprocess.PIPE)
        self.t0 = time.time()
        self._procs = [sl, ff]
        asyncio.create_task(self._pipe(sl, ff))
        asyncio.create_task(self._prune())
        log.info("enregistrement %s → %s", self.streamer.key, self.dir)

    async def _pipe(self, src, dst) -> None:
        try:
            while chunk := await src.stdout.read(1 << 16):
                dst.stdin.write(chunk)
                await dst.stdin.drain()
        finally:
            dst.stdin.close()

    def segments(self) -> list[Segment]:
        """Segments terminés (listés par ffmpeg), avec leur heure murale."""
        lst = self.dir / "list.csv"
        if not lst.exists() or self.t0 is None:
            return []
        segs = []
        for line in lst.read_text().splitlines():
            name, start, end = line.rsplit(",", 2)
            p = self.dir / name
            if p.exists():
                segs.append(Segment(p, self.t0 + float(start), float(end) - float(start)))
        return segs

    async def _prune(self) -> None:
        while self.running:
            await asyncio.sleep(30)
            cutoff = time.time() - self.buffer_s
            for s in self.segments():
                if s.start + s.duration < cutoff:
                    s.path.unlink(missing_ok=True)

    @property
    def running(self) -> bool:
        return bool(self._procs) and self._procs[0].returncode is None

    async def stop(self) -> None:
        for p in self._procs:
            if p.returncode is None:
                p.terminate()
        for p in self._procs:
            await p.wait()
