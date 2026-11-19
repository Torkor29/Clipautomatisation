"""Moteur : surveillance des lives, enregistrement, détection, création des clips, imports, rendus."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

import numpy as np

from . import clipper
from .audio import segment_loudness
from .chat import kick_chat, twitch_chat
from .config import Streamer
from .db import DB, deep_merge
from .detector import Detector, Lexicon, robust_z
from .monitor import LiveMonitor
from .recorder import Recorder
from .review import make_review

log = logging.getLogger(__name__)


def default_edit(settings: dict, trim: tuple[float, float], title: str = "") -> dict:
    return {"trim": list(trim), "style": dict(settings["style"]), "layout": dict(settings["layout"]),
            "hook": dict(settings["hook"]), "title": title, "captions": True, "speed": 1.0}


def auto_title(words: list[dict], streamer: str) -> str:
    """Titre de départ : la phrase la plus « choc » (exclamations / questions), sinon le début."""
    text = " ".join(w["w"] for w in words)
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if 3 <= len(s.split()) <= 12]
    if sents:
        best = max(sents, key=lambda s: (s.count("!") * 2 + s.count("?"), -abs(len(s.split()) - 7)))
        return best[:70]
    return f"{streamer} en PLS 😭" if streamer else "Moment fort 🔥"


class Session:
    def __init__(self, eng: "Engine", streamer: Streamer, row: dict, info: dict):
        self.eng, self.streamer, self.row, self.info = eng, streamer, row, info
        cfg = self.cfg()
        r = cfg["record"]
        self.rec = Recorder(streamer, eng.data / "rec", r["quality"], r["segment_seconds"], r["buffer_minutes"])
        self.det = self._detector(cfg)
        self.stop = asyncio.Event()
        self.tasks: list[asyncio.Task] = []
        self.started = time.time()
        self.clip_times: list[float] = []
        self.chat_msgs = 0

    def cfg(self) -> dict:
        return deep_merge(self.eng.db.settings(), self.row.get("overrides") or {})

    def _detector(self, cfg: dict) -> Detector:
        d = cfg["detect"]
        return Detector(window=d["window_seconds"], baseline_s=d["baseline_minutes"] * 60,
                        threshold=d["threshold"], cooldown=d["cooldown_seconds"], warmup=d["warmup_seconds"],
                        min_signals=d["min_signals"], weights=dict(d["weights"]),
                        lexicon=Lexicon(d["laugh_words"], d["hype_words"], d["keywords"]))

    def apply_settings(self) -> None:
        """Réglages modifiés dans l'interface → appliqués à chaud au live en cours."""
        d = self.cfg()["detect"]
        self.det.threshold, self.det.cooldown = d["threshold"], d["cooldown_seconds"]
        self.det.min_signals, self.det.weights = d["min_signals"], dict(d["weights"])
        self.det.lexicon = Lexicon(d["laugh_words"], d["hype_words"], d["keywords"])

    def _on_msg(self, t, user, text):
        self.chat_msgs += 1
        self.det.add_message(t, user, text)

    async def start(self) -> None:
        await self.rec.start()
        if self.streamer.platform == "twitch":
            self.tasks.append(asyncio.create_task(twitch_chat(self.streamer.channel, self._on_msg, self.stop)))
        elif self.streamer.platform == "kick" and self.info.get("chatroom_id"):
            self.tasks.append(asyncio.create_task(kick_chat(self.info["chatroom_id"], self._on_msg, self.stop)))
        self.tasks += [asyncio.create_task(self._audio_loop()), asyncio.create_task(self._detect_loop())]

    async def _audio_loop(self) -> None:
        seen: set[str] = set()
        while not self.stop.is_set():
            for s in self.rec.segments():
                if s.path.name not in seen:
                    seen.add(s.path.name)
                    try:
                        for t, db in await segment_loudness(str(s.path), s.start):
                            self.det.add_audio(t, db)
                    except Exception:
                        log.debug("audio illisible %s", s.path)
            await asyncio.sleep(2)

    async def _detect_loop(self) -> None:
        while not self.stop.is_set():
            await asyncio.sleep(self.det.window)
            cfg = self.cfg()
            trig = self.det.step(time.time() - cfg["detect"]["chat_delay_seconds"])
            if not trig:
                continue
            self.clip_times = [t for t in self.clip_times if t > time.time() - 3600]
            if len(self.clip_times) >= cfg["detect"]["max_clips_per_hour"]:
                continue
            self.clip_times.append(time.time())
            log.info("🔥 %s score=%s %s", self.streamer.key, trig.score, trig.detail["z"])
            asyncio.create_task(self._clip(trig, cfg))

    async def _clip(self, trig, cfg: dict) -> None:
        c = cfg["clip"]
        pre, post = max(c["pre_roll"], c["max_seconds"]), c["post_roll"] + 5
        await asyncio.sleep(max(trig.t + post + self.rec.seg_s + 5 - time.time(), 0))
        name = f"{self.streamer.channel}_{int(trig.t)}"
        src = self.eng.data / "clips" / name / "source.mp4"
        try:
            await clipper.extract_source(self.rec.segments(), trig.t - pre, trig.t + post, src)
            await self.eng.new_clip(src, peak=pre, streamer=self.streamer.channel,
                                    platform=self.streamer.platform, score=trig.score, detail=trig.detail,
                                    cfg=cfg, origin="live")
        except Exception:
            log.exception("échec du clip")

    def status(self) -> dict:
        tl = list(self.det.timeline)[-90:]
        return {"key": self.streamer.key, "channel": self.streamer.channel, "platform": self.streamer.platform,
                "title": self.info.get("title"), "viewers": self.info.get("viewers"), "since": self.started,
                "chat_msgs": self.chat_msgs, "recording": self.rec.running,
                "threshold": self.det.threshold, "timeline": [[round(t), s] for t, s, _ in tl],
                "last_z": tl[-1][2] if tl else {}}

    async def close(self) -> None:
        self.stop.set()
        for t in self.tasks:
            t.cancel()
        await self.rec.stop()


class Engine:
    def __init__(self, data_dir: Path):
        self.data = data_dir
        self.db = DB(data_dir / "clipauto.db")
        self.sessions: dict[str, Session] = {}
        self.review = make_review(self.on_decision)
        self.cpu = asyncio.Semaphore(1)  # transcriptions/rendus un par un (VPS sans GPU)
        self.monitor: LiveMonitor | None = None

    # ---------- streamers
    def _streamers(self) -> list[Streamer]:
        return [Streamer(r["platform"], r["channel"]) for r in self.db.streamers() if r["enabled"]]

    def _row(self, key: str) -> dict:
        return next((r for r in self.db.streamers() if f"{r['platform']}:{r['channel'].lower()}" == key), {})

    async def on_live(self, s: Streamer, info: dict) -> None:
        await self._notify(f"🔴 **{s.channel}** est en live sur {s.platform} — « {info.get('title') or ''} » "
                           f"→ début de l'enregistrement")
        sess = Session(self, s, self._row(s.key), info)
        self.sessions[s.key] = sess
        await sess.start()

    async def on_offline(self, key: str) -> None:
        sess = self.sessions.pop(key, None)
        if sess:
            await sess.close()
            await self._notify(f"⚫ {sess.streamer.channel} a terminé son live.")

    def settings_changed(self) -> None:
        for k, sess in self.sessions.items():
            sess.row = self._row(k) or sess.row
            sess.apply_settings()

    # ---------- clips
    async def new_clip(self, src: Path, peak: float, streamer: str, platform: str, score: float,
                       detail: dict, cfg: dict, origin: str) -> int:
        c = cfg["clip"]
        async with self.cpu:
            words = await asyncio.to_thread(clipper.transcribe, src, c["whisper_model"], c["language"])
        total = await clipper.probe_duration(src)
        t0, t1 = clipper.smart_trim(words, peak, total, c["min_seconds"], c["max_seconds"],
                                    c["pre_roll"], c["post_roll"], c["snap_to_sentences"])
        kept = [w for w in words if t0 <= w["s"] < t1]
        title = auto_title(kept, streamer)
        thumb = await clipper.thumbnail(src, min(peak, total - 0.5), src.parent / "thumb.jpg")
        cid = self.db.add_clip(streamer=streamer, platform=platform, source=str(src), thumb=str(thumb),
                               score=score, detail=detail, transcript=" ".join(w["w"] for w in kept),
                               words=words, edit=default_edit(cfg, (t0, t1), title), title=title,
                               duration=t1 - t0, origin=origin)
        z = detail.get("z", {})
        if c.get("auto_render", True):
            await self.render_clip(cid)
        clip = self.db.clip(cid)
        msg = (f"🎬 **Clip #{cid}** — {streamer} ({platform}) · score {score} · {t1 - t0:.0f}s\n"
               f"« {title} »\nchat ×{z.get('chat_rate', 0)} · rires ×{z.get('laugh_emotes', 0)} · "
               f"audio ×{z.get('audio', 0)}")
        try:
            await self.review.send_clip(cid, Path(clip["path"] or src), msg)
        except Exception:
            log.exception("envoi Discord")
        return cid

    async def render_clip(self, cid: int) -> None:
        clip = self.db.clip(cid)
        src = Path(clip["source"])
        self.db.update_clip(cid, render_status="rendering", error=None)
        try:
            async with self.cpu:
                out = await clipper.render(src, clip["words"], clip["edit"], src.parent / f"final_{int(time.time())}.mp4")
            old = clip.get("path")
            e = clip["edit"]
            thumb = await clipper.thumbnail(out, min(1.5, (e["trim"][1] - e["trim"][0]) / 2), src.parent / "thumb.jpg")
            self.db.update_clip(cid, path=str(out), thumb=str(thumb), render_status="done", title=e.get("title", ""),
                                duration=(e["trim"][1] - e["trim"][0]) / float(e.get("speed", 1) or 1))
            if old and old != str(out):
                Path(old).unlink(missing_ok=True)
        except Exception as ex:
            log.exception("rendu")
            self.db.update_clip(cid, render_status="error", error=str(ex)[-500:])

    # ---------- import (VOD Twitch/Kick/YouTube ou fichier)
    async def import_video(self, jid: int, path: Path | None, url: str | None, opts: dict) -> None:
        cfg = deep_merge(self.db.settings(), {"clip": opts.get("clip", {})})
        try:
            work = self.data / "imports" / str(jid)
            work.mkdir(parents=True, exist_ok=True)
            if url:
                self.db.update_job(jid, message="téléchargement…", progress=0.05)
                await clipper.run("yt-dlp", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
                                  "--merge-output-format", "mp4", "-o", str(work / "video.%(ext)s"), url)
                path = next(work.glob("video.*"))
            assert path
            self.db.update_job(jid, message="analyse audio…", progress=0.2)
            n = int(opts.get("max_clips", 5))
            peaks = await self.find_peaks(path, n, cfg)
            for i, (t, score, z) in enumerate(peaks):
                self.db.update_job(jid, message=f"clip {i + 1}/{len(peaks)}…", progress=0.3 + 0.7 * i / max(len(peaks), 1))
                c = cfg["clip"]
                pre = max(c["pre_roll"], c["max_seconds"])
                dst = self.data / "clips" / f"import{jid}_{int(t)}" / "source.mp4"
                await clipper.cut_file(path, t - pre, t + c["post_roll"] + 5, dst)
                await self.new_clip(dst, peak=min(pre, t), streamer=opts.get("streamer", ""),
                                    platform="import", score=score, detail={"z": z}, cfg=cfg, origin="import")
            self.db.update_job(jid, status="done", progress=1, message=f"{len(peaks)} clips créés")
        except Exception as ex:
            log.exception("import")
            self.db.update_job(jid, status="error", message=str(ex)[-300:])

    async def find_peaks(self, path: Path, n: int, cfg: dict) -> list[tuple[float, float, dict]]:
        """Moments forts d'une vidéo sans chat : pics de volume + rafales (rires/cris) + mots-clés dits."""
        pcm = await asyncio.to_thread(clipper.load_pcm, path)
        hop = 16000 // 2
        rms = np.array([np.sqrt(np.mean(pcm[i:i + hop] ** 2)) + 1e-9 for i in range(0, len(pcm) - hop, hop)])
        db = 20 * np.log10(rms)
        win = 20  # 10 s
        loud = np.array([np.percentile(db[i:i + win], 90) for i in range(0, len(db) - win, 4)])
        burst = np.array([np.std(np.diff(db[i:i + win])) for i in range(0, len(db) - win, 4)])
        score = np.zeros(len(loud))
        for arr, w in ((loud, 1.0), (burst, 0.8)):
            med, mad = np.median(arr), np.median(np.abs(arr - np.median(arr))) * 1.4826 + 1e-6
            score += w * np.clip((arr - med) / mad, 0, None)
        kws = [k.lower() for k in cfg["detect"]["keywords"]]
        if kws:  # mots-clés prononcés (transcription complète, plus lent)
            async with self.cpu:
                words = await asyncio.to_thread(clipper.transcribe, path, cfg["clip"]["whisper_model"],
                                                cfg["clip"]["language"])
            for w in words:
                if any(k in w["w"].lower() for k in kws):
                    i = int(w["s"] / 2)
                    if 0 <= i < len(score):
                        score[max(i - 2, 0):i + 2] += 3
        gap = int(cfg["clip"]["max_seconds"] / 2) + 5
        picks: list[tuple[float, float, dict]] = []
        for i in np.argsort(-score):
            t = i * 2 + 5
            if all(abs(t - p[0]) > gap for p in picks) and score[i] > 0:
                picks.append((float(t), round(float(score[i]), 2), {"audio": round(float(score[i]), 2)}))
            if len(picks) >= n:
                break
        return sorted(picks)

    # ---------- validation / publication
    async def on_decision(self, cid: int, approved: bool) -> None:
        if not self.db.clip(cid):
            return
        if not approved:
            self.db.update_clip(cid, status="rejected")
            return
        self.db.update_clip(cid, status="approved")
        if self.db.settings()["publish"].get("auto_publish"):
            await self.publish(cid)

    async def publish(self, cid: int, caption: str | None = None) -> str:
        from .publisher import PostForMe
        s = self.db.settings()["publish"]
        clip = self.db.clip(cid)
        try:
            if clip["render_status"] != "done":
                await self.render_clip(cid)
                clip = self.db.clip(cid)
            pub = PostForMe(s["social_accounts"], s["caption_template"])
            text = caption or s["caption_template"].format(title=clip["title"] or "", streamer=clip["streamer"],
                                                           platform=clip["platform"])
            pid = await pub.publish(Path(clip["path"]), clip["streamer"], clip["platform"], text)
            self.db.update_clip(cid, status="published", post_id=pid)
            await self._notify(f"📤 Clip #{cid} publié.")
            return pid
        except Exception as e:
            self.db.update_clip(cid, status="error", error=str(e)[-500:])
            raise

    async def _notify(self, text: str) -> None:
        try:
            await self.review.notify(text)
        except Exception:
            log.exception("notification")

    async def run(self) -> None:
        try:
            await self.review.start()
        except Exception:
            log.exception("Discord indisponible, on continue sans")
            from .review import ConsoleReview
            self.review = ConsoleReview()
        self.monitor = LiveMonitor(self._streamers, lambda: self.db.settings()["poll_seconds"],
                                   self.on_live, self.on_offline)
        await self.monitor.run()
