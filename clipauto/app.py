"""Orchestrateur : relie monitor → recorder + chat → detector → clipper → review → publish."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from .audio import segment_loudness
from .chat import kick_chat, twitch_chat
from .clipper import make_clip
from .config import Config, Streamer
from .detector import Detector
from .monitor import LiveMonitor
from .recorder import Recorder
from .review import make_review
from .store import Store

log = logging.getLogger(__name__)
# décalage d'analyse : le segment vidéo doit être écrit et le chat réagit avec retard
ANALYSIS_LAG = 30


class Session:
    """Un live en cours d'un streamer."""

    def __init__(self, app: "App", streamer: Streamer, info: dict):
        self.app, self.streamer, self.info = app, streamer, info
        c = app.cfg
        self.rec = Recorder(streamer, c.data_dir / "rec", c.record.get("quality", "best"),
                            c.record.get("segment_seconds", 10), c.record.get("buffer_minutes", 15))
        d = c.detect
        self.det = Detector(window=d.get("window_seconds", 10), baseline_s=d.get("baseline_minutes", 10) * 60,
                            threshold=d.get("threshold", 2.0), cooldown=d.get("cooldown_seconds", 90),
                            warmup=d.get("warmup_seconds", 120), **({"weights": d["weights"]} if "weights" in d else {}))
        self.stop = asyncio.Event()
        self.tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        await self.rec.start()
        if self.streamer.platform == "twitch":
            self.tasks.append(asyncio.create_task(twitch_chat(self.streamer.channel, self.det.add_message, self.stop)))
        elif self.streamer.platform == "kick" and self.info.get("chatroom_id"):
            self.tasks.append(asyncio.create_task(kick_chat(self.info["chatroom_id"], self.det.add_message, self.stop)))
        self.tasks += [asyncio.create_task(self._audio_loop()), asyncio.create_task(self._detect_loop())]

    async def _audio_loop(self) -> None:
        seen: set[str] = set()
        while not self.stop.is_set():
            for s in self.rec.segments():
                if s.path.name not in seen:
                    seen.add(s.path.name)
                    for t, db in await segment_loudness(str(s.path), s.start):
                        self.det.add_audio(t, db)
            await asyncio.sleep(2)

    async def _detect_loop(self) -> None:
        post = self.app.cfg.clip.get("post_roll", 20)
        while not self.stop.is_set():
            await asyncio.sleep(self.det.window)
            trig = self.det.step(time.time() - ANALYSIS_LAG)
            if trig:
                log.info("🔥 moment fort %s score=%s %s", self.streamer.key, trig.score, trig.detail["z"])
                asyncio.create_task(self._clip(trig, post))

    async def _clip(self, trig, post: float) -> None:
        # attendre que le post-roll soit enregistré
        await asyncio.sleep(max(trig.t + post + self.rec.seg_s + 5 - time.time(), 0))
        c = self.app.cfg.clip
        out = self.app.cfg.data_dir / "clips" / f"{self.streamer.channel}_{int(trig.t)}.mp4"
        try:
            res = await make_clip(self.rec.segments(), trig.t, out, c.get("pre_roll", 40), post,
                                  c.get("vertical", True), c.get("captions", True), c.get("whisper_model", "small"), c.get("language"))
        except Exception:
            log.exception("échec du clip")
            return
        cid = self.app.store.add(self.streamer.channel, self.streamer.platform, res["path"], trig.score,
                                 trig.detail, res["transcript"])
        z = trig.detail["z"]
        text = (f"🎬 **Clip #{cid}** — {self.streamer.channel} ({self.streamer.platform}) · score {trig.score}\n"
                f"chat ×{z.get('chat_rate', 0)} · rires ×{z.get('laugh_emotes', 0)} · audio ×{z.get('audio', 0)}\n"
                f"> {res['transcript'][:300]}")
        await self.app.review.send_clip(cid, Path(res["path"]), text)

    async def close(self) -> None:
        self.stop.set()
        for t in self.tasks:
            t.cancel()
        await self.rec.stop()


class App:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.store = Store(cfg.data_dir / "clips.db")
        self.review = make_review(self.on_decision)
        self.sessions: dict[str, Session] = {}
        self.publisher = None
        if cfg.publish.get("social_accounts"):
            from .publisher import PostForMe
            self.publisher = PostForMe(cfg.publish["social_accounts"], cfg.publish.get("caption_template", "{streamer}"))

    async def on_live(self, s: Streamer, info: dict) -> None:
        await self.review.notify(f"🔴 **{s.channel}** est en live sur {s.platform} — « {info.get('title') or ''} » "
                                 f"→ début de l'enregistrement")
        sess = Session(self, s, info)
        self.sessions[s.key] = sess
        await sess.start()

    async def on_offline(self, s: Streamer) -> None:
        sess = self.sessions.pop(s.key, None)
        if sess:
            await sess.close()
            await self.review.notify(f"⚫ {s.channel} a terminé son live.")

    async def on_decision(self, clip_id: int, approved: bool) -> None:
        row = self.store.get(clip_id)
        if not row:
            return
        if not approved:
            self.store.set(clip_id, status="rejected")
            return
        self.store.set(clip_id, status="approved")
        if not self.publisher:
            await self.review.notify(f"Clip #{clip_id} approuvé (publication non configurée).")
            return
        try:
            pid = await self.publisher.publish(Path(row["path"]), row["streamer"], row["platform"])
            self.store.set(clip_id, status="published", post_id=pid)
            await self.review.notify(f"📤 Clip #{clip_id} publié (post {pid}).")
        except Exception as e:
            log.exception("publication")
            self.store.set(clip_id, status="error", error=str(e))
            await self.review.notify(f"⚠️ Échec publication clip #{clip_id} : {e}")

    async def run(self) -> None:
        await self.review.start()
        mon = LiveMonitor(self.cfg.streamers, self.cfg.poll_seconds, self.on_live, self.on_offline)
        await mon.run()
