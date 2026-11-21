"""Moteur : surveillance des lives, enregistrement, détection, création des clips, imports, rendus."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

import numpy as np

from . import clipper, facecam, virality  # noqa: F401 (facecam importe cv2 au démarrage)
from collections import deque
from .audio import segment_loudness
from .chat import kick_chat, twitch_chat
from .config import Streamer
from .db import DB, deep_merge, profile_values


def effective_settings(settings: dict, overrides: dict) -> dict:
    """Priorité : réglages globaux  <  profil choisi pour ce streamer  <  réglages avancés du streamer.
    Les mots-clés du streamer s'AJOUTENT à ceux du global."""
    import copy
    o = copy.deepcopy(overrides or {})
    prof = o.pop("profile", None)
    out = deep_merge(settings, profile_values(prof)) if prof else settings
    extra_kw = (o.get("detect") or {}).pop("keywords", None) if o.get("detect") else None
    out = deep_merge(out, o)
    if extra_kw:
        out["detect"]["keywords"] = list(dict.fromkeys(list(settings["detect"]["keywords"]) + list(extra_kw)))
    return out
from .detector import Detector, Lexicon, robust_z
from .monitor import LiveMonitor
from .recorder import Recorder
from .review import make_review

log = logging.getLogger(__name__)


def default_edit(settings: dict, trim: tuple[float, float], title: str = "") -> dict:
    tr = settings.get("compilation", {}).get("transition", "fade")
    return {"trim": list(trim), "segments": [{"s": trim[0], "e": trim[1], "effect": "none",
                                               "transition": {"type": tr, "duration": 0.4}}],
            "style": dict(settings["style"]), "layout": dict(settings["layout"]),
            "hook": dict(settings["hook"]), "title": title, "captions": True, "speed": 1.0}


def auto_title(words: list[dict], streamer: str) -> str:
    """Titre de départ : la phrase courte la plus « choc » (émotion, question, exclamation)."""
    from .virality import EMOTION
    text = " ".join(w["w"] for w in words)
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if 3 <= len(s.split()) <= 10]

    def punch(s: str) -> float:
        toks = [re.sub(r"[^\w'’-]", "", t.lower()) for t in s.split()]
        return 2 * s.count("!") + 1.5 * s.count("?") + sum(t in EMOTION for t in toks) - 0.15 * abs(len(toks) - 6)

    if sents:
        best = max(sents, key=punch)
        best = best if len(best) <= 60 else best[:57].rsplit(" ", 1)[0] + "…"
        return re.sub(r"\s+([!?:;])", "\u00a0\\1", best)  # pas de « ! » tout seul sur une ligne
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
        self.chat_log: deque = deque(maxlen=5000)
        self.pending: dict | None = None  # clip en préparation (on y ajoute les pics qui suivent de près)  # (t, user, texte) pour expliquer les clips

    def cfg(self) -> dict:
        return effective_settings(self.eng.db.settings(), self.row.get("overrides") or {})

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
        self.chat_log.append((t, user, text))
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
            # on analyse le chat d'il y a 15 s (le temps que la vidéo/audio correspondante soit écrite)
            trig = self.det.step(time.time() - 15, float(cfg["detect"]["chat_delay_seconds"]))
            if not trig:
                continue
            pd = self.pending
            if pd and not pd["started"] and trig.t - pd["peaks"][-1] < 60:
                # un autre pic juste après : même histoire → même clip
                pd["peaks"].append(trig.t)
                if trig.score > pd["trig"].score:
                    pd["trig"] = trig
                log.info("🔥 %s pic supplémentaire regroupé (%d pics)", self.streamer.key, len(pd["peaks"]))
                continue
            self.clip_times = [t for t in self.clip_times if t > time.time() - 3600]
            if len(self.clip_times) >= cfg["detect"]["max_clips_per_hour"]:
                continue
            self.clip_times.append(time.time())
            log.info("🔥 %s score=%s %s", self.streamer.key, trig.score, trig.detail["z"])
            self.pending = {"peaks": [trig.t], "trig": trig, "started": False}
            asyncio.create_task(self._clip(self.pending, cfg))

    async def _clip(self, pd: dict, cfg: dict) -> None:
        c = cfg["clip"]
        ctx_before, ctx_after = 60.0, 40.0  # contexte analysé autour des pics (pour trouver début / fin)
        while True:  # on attend la fin de la réaction au DERNIER pic (d'autres pics peuvent s'ajouter)
            due = pd["peaks"][-1] + ctx_after + self.rec.seg_s + 5
            if time.time() >= due:
                break
            await asyncio.sleep(min(due - time.time(), 5))
        pd["started"] = True
        if self.pending is pd:
            self.pending = None
        trig = pd["trig"]
        react = trig.detail.get("reaction", 0)
        lo, hi = trig.t - 20, trig.t + react + 15
        msgs = [(t, u, m) for t, u, m in self.chat_log if lo <= t <= hi]
        lex = self.det.lexicon
        def prio(x):
            la, hy, kw = lex.classify(x[2])
            return la + hy + 2 * kw
        if len(msgs) > 60:  # garde les messages les plus parlants, en ordre chronologique
            msgs = sorted(sorted(msgs, key=prio, reverse=True)[:60])
        def tag(m):
            la, hy, kw = lex.classify(m)
            return "mot-clé" if kw else "rire" if la else "hype" if hy else ""
        trig.detail["chat"] = [{"t": round(t - trig.t, 1), "u": u, "m": m[:200], "tag": tag(m)} for t, u, m in msgs]
        trig.detail["chat_window"] = [round(lo - trig.t, 1), round(hi - trig.t, 1)]
        trig.detail["stream"] = {"title": self.info.get("title"), "game": self.info.get("game")}
        name = f"{self.streamer.channel}_{int(trig.t)}"
        src = self.eng.data / "clips" / name / "source.mp4"
        t_src = pd["peaks"][0] - ctx_before
        curve = [(round(t - react - t_src, 1), sc) for t, sc, _ in self.det.timeline
                 if t_src - 5 <= t - react <= pd["peaks"][-1] + ctx_after + 5]
        try:
            await clipper.extract_source(self.rec.segments(), t_src, pd["peaks"][-1] + ctx_after, src)
            await self.eng.new_clip(src, peak=trig.t - t_src, streamer=self.streamer.channel,
                                    platform=self.streamer.platform, score=trig.score, detail=trig.detail,
                                    cfg=cfg, origin="live", peaks=[p - t_src for p in pd["peaks"]], curve=curve)
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
        self._last_curve: list | None = None

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
                       detail: dict, cfg: dict, origin: str, progress=None, peaks: list | None = None,
                       curve: list | None = None) -> int:
        c = cfg["clip"]
        say = progress or (lambda m: None)
        say("transcription de la voix (l'étape la plus longue)…")
        async with self.cpu:
            words = await asyncio.to_thread(clipper.transcribe, src, c["whisper_model"], c["language"],
                                            c.get("streamer_only", True))
        total = await clipper.probe_duration(src)
        story = None
        if curve is not None:
            from .story import story_window
            story = story_window(words, peaks or [peak], curve, total, c["min_seconds"], c["max_seconds"],
                                 cfg["detect"]["threshold"], c.get("remove_silences", True))
            t0, t1 = story["segments"][0][0], story["segments"][-1][1]
        else:
            t0, t1 = clipper.smart_trim(words, peak, total, c["min_seconds"], c["max_seconds"],
                                        c["pre_roll"], c["post_roll"], c["snap_to_sentences"])
        kept = [w for w in words if t0 <= w["s"] < t1 and not w.get("skip")]
        from .titles import suggest
        title_opts = suggest(kept, streamer, detail, (detail.get("stream") or {}).get("game"))
        title = title_opts[0] if title_opts else auto_title(kept, streamer)
        # ---- pourquoi ce clip : signaux + analyse du texte (+ juge IA optionnel, plafonné)
        settings = self.db.settings()
        analysis = virality.analyze_text(words, t0, t1, cfg["detect"]["keywords"])
        sig = virality.signal_score(score) if detail.get("z") else None
        usage = dict(settings.get("ai_usage") or {})
        llm = await asyncio.to_thread(virality.llm_judge, " ".join(w["w"] for w in kept), streamer, platform,
                                      settings["ai"], usage)
        if usage != settings.get("ai_usage"):
            self.db.save_settings({"ai_usage": usage})
        if llm and settings["ai"].get("use_title") and llm.get("title"):
            title = llm["title"]
        viral = virality.combine(sig, analysis["score"], llm["score"] if llm else None)
        if llm and llm.get("title"):
            title_opts = [llm["title"]] + [t for t in title_opts if t != llm["title"]]
        if story:
            detail["story"] = story
        detail = {**detail, "title_options": title_opts, "analysis": analysis, "signals": virality.explain_signals(detail),
                  "signal_score": sig, "llm": llm, "viral": viral, "peak_src": round(peak, 2)}
        layout = dict(cfg["layout"])
        vw, vh = await clipper.probe_size(src)
        vertical = vh > vw * 1.4
        if vertical:  # déjà en 9:16 : on garde l'image entière
            layout["mode"] = "fill"
            layout["focus"] = {"x": 0.5}
            detail["vertical_source"] = True
        if layout.get("mode") in ("split", "pip") and layout.get("auto_facecam", True):
            fc = await asyncio.to_thread(facecam.detect, src)
            if fc:
                layout["facecam"] = fc["facecam"]
                detail["facecam"] = fc
            else:  # pas de cam visible (jeu plein écran) : pas de cadre vide ou mal placé
                layout["mode"] = "blur"
                detail["facecam"] = {"none": True}
        min_v = int(c.get("min_viral", 0) or 0)
        # un import est une demande explicite : on garde tout (le score reste visible) ; seuls les clips live sont filtrés
        rejected = viral < min_v and origin == "live"
        thumb = await clipper.thumbnail(src, min(peak, total - 0.5), src.parent / "thumb.jpg")
        cid = self.db.add_clip(streamer=streamer, platform=platform, source=str(src), thumb=str(thumb),
                               score=score, detail=detail, transcript=" ".join(w["w"] for w in kept),
                               words=words, edit={**default_edit(cfg, (t0, t1), title), "layout": layout,
                                                  **({"segments": [{"s": a, "e": b, "effect": "none",
                                                                    "transition": {"type": "cut", "duration": 0.4}}
                                                                   for a, b in story["segments"]]} if story else {}),
                                                  # une vidéo verticale a souvent déjà ses sous-titres incrustés
                                                  **({"captions": False} if vertical else {})},
                               title=title, duration=(sum(b - a for a, b in story["segments"]) if story else t1 - t0),
                               origin=origin,
                               status="rejected" if rejected else "pending",
                               error=f"Écarté automatiquement : score viral {viral} < minimum {min_v}" if rejected else None)
        if rejected:
            log.info("clip #%s écarté (score %s < %s)", cid, viral, min_v)
            return cid
        z = detail.get("z", {})
        say("rendu vidéo 9:16…")
        if c.get("auto_render", True):
            await self.render_clip(cid)
        clip = self.db.clip(cid)
        why = " · ".join(r for r in analysis["reasons"][:2])
        msg = (f"🎬 **Clip #{cid}** — {streamer} ({platform}) · score viral {viral}/100 · {t1 - t0:.0f}s\n"
               f"{why}\n"
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
                out = await clipper.render(src, clip["words"], clip["edit"], src.parent / f"final_{int(time.time())}.mp4",
                                           keywords=self.db.settings()["detect"]["keywords"], data_dir=self.data)
            old = clip.get("path")
            e = clip["edit"]
            thumb = await clipper.thumbnail(out, min(1.5, clipper.output_duration(e) / 2), src.parent / "thumb.jpg")
            self.db.update_clip(cid, path=str(out), thumb=str(thumb), render_status="done", title=e.get("title", ""),
                                duration=clipper.output_duration(e))
            if old and old != str(out):
                Path(old).unlink(missing_ok=True)
        except Exception as ex:
            log.exception("rendu")
            self.db.update_clip(cid, render_status="error", error=str(ex)[-500:])

    # ---------- résumé de live (compilation de plusieurs clips)
    async def build_compilation(self, jid: int, clip_ids: list[int], title: str, transition: str,
                                tdur: float, max_each: float | None, effect: str = "none",
                                intro_text: bool = True) -> None:
        cfg = self.db.settings()
        try:
            clips = [c for c in (self.db.clip(i) for i in clip_ids) if c]
            if len(clips) < 2:
                raise RuntimeError("il faut au moins 2 clips")
            work = self.data / "clips" / f"compil_{jid}"
            work.mkdir(parents=True, exist_ok=True)
            parts, words, segs, t = [], [], [], 0.0
            for n, c in enumerate(clips):
                self.db.update_job(jid, message=f"préparation {n + 1}/{len(clips)}…", progress=0.1 + 0.5 * n / len(clips))
                for k, sg in enumerate(clipper.segments_of(c["edit"])):
                    s0, s1 = sg["s"], sg["e"]
                    if max_each and k == 0 and s1 - s0 > max_each:  # garde la fin (la chute) du moment
                        s0 = s1 - max_each
                    part = await clipper.normalize_part(Path(c["source"]), s0, s1, work / f"p{len(parts):03}.mp4")
                    d = await clipper.probe_duration(part)
                    parts.append(part)
                    words += [{**w, "s": round(t + w["s"] - s0, 3), "e": round(t + min(w["e"], s1) - s0, 3)}
                              for w in c["words"] if s0 <= w["s"] < s1]
                    segs.append({"s": round(t, 3), "e": round(t + d, 3), "effect": effect if effect != "none" else sg.get("effect", "none"),
                                 "transition": {"type": transition if k == 0 else
                                                (sg.get("transition") or {}).get("type", "cut"),
                                                "duration": tdur}, "from_clip": c["id"]})
                    t += d
            self.db.update_job(jid, message="assemblage…", progress=0.65)
            src = await clipper.concat_parts(parts, work / "source.mp4")
            for p in parts:
                p.unlink(missing_ok=True)
            first = clips[0]
            edit = default_edit(cfg, (0, t), title)
            edit.update(segments=segs, layout=dict(first["edit"].get("layout") or cfg["layout"]))
            edit["hook"]["enabled"] = intro_text
            thumb = await clipper.thumbnail(src, 1, work / "thumb.jpg")
            cid = self.db.add_clip(streamer=first["streamer"], platform=first["platform"], source=str(src),
                                   thumb=str(thumb), score=max(c["score"] or 0 for c in clips),
                                   detail={"compilation": clip_ids}, transcript=" ".join(w["w"] for w in words),
                                   words=words, edit=edit, title=title, duration=clipper.output_duration(edit),
                                   origin="compilation")
            self.db.update_job(jid, message="rendu…", progress=0.75)
            await self.render_clip(cid)
            self.db.update_job(jid, status="done", progress=1, message=f"résumé créé → clip #{cid}")
        except Exception as ex:
            log.exception("compilation")
            self.db.update_job(jid, status="error", message=str(ex)[-300:])

    def best_clips(self, streamer: str | None, hours: float, n: int, mode: str = "recent") -> list[int]:
        """`recent` = les N derniers clips faits ; `best` = les N meilleurs scores viraux."""
        since = time.time() - hours * 3600
        rows = [c for c in self.db.clips(limit=2000) if c["created"] >= since and c["status"] != "rejected"
                and c["origin"] != "compilation" and (not streamer or c["streamer"] == streamer)]
        if mode == "best":
            best = sorted(rows, key=lambda c: -((c.get("detail") or {}).get("viral") or c["score"] or 0))[:n]
        else:
            best = sorted(rows, key=lambda c: -c["created"])[:n]
        return [c["id"] for c in sorted(best, key=lambda c: c["created"])]  # ordre chronologique

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
                await clipper.cut_file(path, t - pre, t + 40, dst)
                lbl = f"clip {i + 1}/{len(peaks)}"
                t_src = max(t - pre, 0)
                curve = [(round(ct - t_src, 1), cv) for ct, cv in (self._last_curve or []) if t_src - 5 <= ct <= t + 45]
                await self.new_clip(dst, peak=min(pre, t), streamer=opts.get("streamer", ""), curve=curve,
                                    platform="import", score=score, detail={"z": z}, cfg=cfg, origin="import",
                                    progress=lambda m, lbl=lbl: self.db.update_job(jid, message=f"{lbl} : {m}"))
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
        self._last_curve = [(float(i * 2 + 5), round(float(v) / 2, 2)) for i, v in enumerate(score)]
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
