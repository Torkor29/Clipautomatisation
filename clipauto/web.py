"""API + interface web (FastAPI). Lancement : python -m clipauto web"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import unquote
import base64
import logging
import os
import secrets
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .captions import BASE, FONTS, LINE_ANIMS, PRESETS, SFX, WORD_ANIMS, em_ratio
from .clipper import EFFECTS, TRANSITIONS
from .config import load_dotenv
from .db import DEFAULT_SETTINGS, PROFILES, profile_values
from .engine import Engine

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
PLATFORMS = ("twitch", "kick", "youtube")


def create_app(data_dir: Path | None = None, start_engine: bool = True) -> FastAPI:
    load_dotenv()
    data = Path(data_dir or os.environ.get("DATA_DIR", "data"))
    eng = Engine(data)
    tasks: set[asyncio.Task] = set()

    def bg(coro):
        t = asyncio.create_task(coro)
        tasks.add(t)
        t.add_done_callback(tasks.discard)

    @asynccontextmanager
    async def lifespan(_app):
        if start_engine:
            bg(eng.run())
        yield
        for k in list(eng.sessions):
            await eng.on_offline(k)

    app = FastAPI(title="ClipAuto", lifespan=lifespan)
    app.state.engine = eng
    password = (os.environ.get("APP_PASSWORD") or "").strip().strip("\"'") or None  # tolère espaces / guillemets

    # front sur Vercel → appels depuis une autre origine (CORS). L'accès est protégé par le jeton.
    from fastapi.middleware.cors import CORSMiddleware
    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
    PUBLIC = ("/api/health",)

    @app.middleware("http")
    async def auth(request: Request, call_next):
        path = request.scope["path"]
        tok = None
        m = re.match(r"^/t/([^/]+)(/.*)$", path)  # médias : /t/<jeton>/media/... (img/video sans en-tête)
        if m:
            tok = unquote(m.group(1))
            request.scope["path"] = m.group(2)
            request.scope["raw_path"] = m.group(2).encode()
            path = m.group(2)
        protected = path.startswith(("/api/", "/media/", "/assets/")) and path not in PUBLIC
        if password and protected and request.method != "OPTIONS":
            h = request.headers.get("authorization", "")
            if h.startswith("Bearer "):
                tok = h[7:]
            elif h.startswith("Basic "):
                try:
                    tok = base64.b64decode(h[6:]).decode().split(":", 1)[1]
                except Exception:
                    tok = None
            if not tok or not secrets.compare_digest(tok, password):
                return JSONResponse({"detail": "Connexion requise"}, status_code=401)
        resp = await call_next(request)
        if path == "/" or path.endswith((".html", ".js", ".css")):
            resp.headers["Cache-Control"] = "no-cache"  # toujours la dernière version de l'interface
        return resp

    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"])

    @app.get("/api/health")
    def health():
        return {"ok": True}

    def clip_or_404(cid: int) -> dict:
        c = eng.db.clip(cid)
        if not c:
            raise HTTPException(404, "clip introuvable")
        return c

    # ------------------------------------------------------------ état général
    @app.get("/api/state")
    def state():
        live = {k: s.status() for k, s in eng.sessions.items()}
        streamers = []
        for r in eng.db.streamers():
            key = f"{r['platform']}:{r['channel'].lower()}"
            streamers.append({**r, "live": key in live, "session": live.get(key)})
        clips = eng.db.clips(limit=1000)
        counts = {s: sum(c["status"] == s for c in clips) for s in ("pending", "approved", "published", "rejected")}
        return {"streamers": streamers, "jobs": eng.db.jobs(), "counts": counts,
                "ai_usage": eng.db.settings().get("ai_usage") or {},
                "integrations": {"gemini": bool(os.environ.get("GEMINI_API_KEY")),
                                 "twitch": bool(os.environ.get("TWITCH_CLIENT_ID")),
                                 "discord": bool(os.environ.get("DISCORD_BOT_TOKEN")),
                                 "postforme": bool(os.environ.get("POST_FOR_ME_API_KEY"))}}

    @app.get("/api/meta")
    def meta():
        from .llm import PROVIDERS
        llm_info = {k: {"label": v["label"], "model": v["model"], "key": v["key"],
                        "has_key": v["key"] is None or bool(os.environ.get(v["key"]))} for k, v in PROVIDERS.items()}
        return {"llm": llm_info, "profiles": PROFILES, "fonts": list(FONTS), "presets": PRESETS, "defaults": DEFAULT_SETTINGS, "platforms": PLATFORMS,
                "transitions": TRANSITIONS, "effects": EFFECTS, "caption_base": BASE,
                "font_ratio": {f: em_ratio(f) for f in FONTS}, "word_anims": WORD_ANIMS,
                "line_anims": LINE_ANIMS, "sfx": SFX, "ovl_anims": ovl.ANIM_IN}

    # ------------------------------------------------------------ réglages
    @app.get("/api/settings")
    def get_settings():
        return eng.db.settings()

    @app.put("/api/settings")
    def put_settings(data: dict = Body(...)):
        s = eng.db.save_settings(data)
        eng.settings_changed()
        return s

    @app.post("/api/settings/profile")
    def set_profile(name: str = Body(..., embed=True)):
        if name not in PROFILES:
            raise HTTPException(400, "profil inconnu")
        s2 = eng.db.save_settings({"profile": name, **profile_values(name)})
        eng.settings_changed()
        return s2

    @app.post("/api/settings/reset")
    def reset_settings(section: str = Body(..., embed=True)):
        if section not in DEFAULT_SETTINGS:
            raise HTTPException(400, "section inconnue")
        s = eng.db.save_settings({section: DEFAULT_SETTINGS[section]})
        eng.settings_changed()
        return s

    # ------------------------------------------------------------ streamers
    @app.post("/api/streamers")
    def add_streamer(platform: str = Body(...), channel: str = Body(...)):
        from .db import clean_channel
        channel = clean_channel(platform, channel)
        if platform not in PLATFORMS or not channel:
            raise HTTPException(400, "plateforme ou chaîne invalide")
        eng.db.add_streamer(platform, channel)
        return {"ok": True}

    @app.patch("/api/streamers/{sid}")
    def patch_streamer(sid: int, data: dict = Body(...)):
        eng.db.update_streamer(sid, **{k: v for k, v in data.items() if k in ("enabled", "overrides")})
        eng.settings_changed()
        return {"ok": True}

    @app.delete("/api/streamers/{sid}")
    def del_streamer(sid: int):
        eng.db.delete_streamer(sid)
        return {"ok": True}

    # ------------------------------------------------------------ clips
    @app.get("/api/clips")
    def list_clips(status: str | None = None):
        return eng.db.clips(status)

    @app.get("/api/clips/{cid}")
    def get_clip(cid: int):
        return clip_or_404(cid)

    @app.patch("/api/clips/{cid}")
    def patch_clip(cid: int, data: dict = Body(...)):
        clip_or_404(cid)
        allowed = {k: v for k, v in data.items() if k in ("edit", "words", "title", "status")}
        if "edit" in allowed and "title" in allowed["edit"]:
            allowed["title"] = allowed["edit"]["title"]
        eng.db.update_clip(cid, **allowed)
        return {"ok": True}

    @app.post("/api/clips/{cid}/render")
    async def render(cid: int):
        clip_or_404(cid)
        eng.db.update_clip(cid, render_status="queued")
        bg(eng.render_clip(cid))
        return {"ok": True}

    @app.post("/api/clips/{cid}/retranscribe")
    async def retranscribe(cid: int, language: str | None = Body(None, embed=True)):
        c = clip_or_404(cid)
        cfg = eng.db.settings()["clip"]
        jid = eng.db.add_job("transcribe", f"Re-transcription du clip #{cid}")

        async def work():
            from . import clipper
            try:
                eng.db.update_job(jid, message="en attente du processeur…", progress=0.1)
                async with eng.cpu:
                    eng.db.update_job(jid, message="transcription…", progress=0.3)
                    words = await asyncio.to_thread(clipper.transcribe, Path(c["source"]), cfg["whisper_model"],
                                                    language if language is not None else cfg["language"],
                                                    cfg.get("streamer_only", True))
                eng.db.update_clip(cid, words=words)
                eng.db.update_job(jid, status="done", progress=1, message=f"{len(words)} mots")
            except Exception as e:
                log.exception("re-transcription")
                eng.db.update_job(jid, status="error", message=str(e)[-300:])
        bg(work())
        return {"job": jid}

    @app.get("/api/clips/{cid}/titles")
    def clip_titles(cid: int):
        from .clipper import segments_of
        from .titles import suggest
        c = clip_or_404(cid)
        segs = segments_of(c["edit"]) if c.get("edit") else []
        kept = [w for w in c["words"] if any(g["s"] <= w["s"] < g["e"] for g in segs)] or c["words"]
        d = c.get("detail") or {}
        return suggest(kept, c["streamer"] or "", d, (d.get("stream") or {}).get("game"))

    @app.post("/api/clips/{cid}/facecam")
    async def detect_facecam(cid: int):
        from . import facecam
        c = clip_or_404(cid)
        r = await asyncio.to_thread(facecam.detect, Path(c["source"]))
        if not r:
            raise HTTPException(404, "aucun visage détecté")
        return r

    @app.post("/api/clips/{cid}/approve")
    async def approve(cid: int):
        clip_or_404(cid)
        await eng.on_decision(cid, True)
        return {"ok": True}

    @app.post("/api/clips/{cid}/reject")
    async def reject(cid: int):
        clip_or_404(cid)
        await eng.on_decision(cid, False)
        return {"ok": True}

    @app.post("/api/clips/{cid}/publish")
    async def publish(cid: int, caption: str | None = Body(None, embed=True)):
        clip_or_404(cid)
        try:
            return {"post_id": await eng.publish(cid, caption)}
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/clips/{cid}")
    def delete_clip(cid: int):
        c = clip_or_404(cid)
        d = Path(c["source"]).parent
        if d.is_dir() and data.resolve() in d.resolve().parents:
            shutil.rmtree(d, ignore_errors=True)
        eng.db.delete_clip(cid)
        return {"ok": True}

    @app.get("/media/{cid}/{kind}")
    def media(cid: int, kind: str, dl: int = 0):
        c = clip_or_404(cid)
        p = {"source": c["source"], "final": c["path"], "thumb": c["thumb"]}.get(kind)
        if not p or not Path(p).exists():
            raise HTTPException(404)
        name = f"clip_{cid}_{(c['streamer'] or 'clip')}.mp4" if dl else None
        return FileResponse(p, filename=name)

    # ------------------------------------------------------------ import
    @app.post("/api/import")
    async def import_video(url: str | None = Form(None), streamer: str = Form(""),
                           max_clips: int = Form(5), min_seconds: int | None = Form(None),
                           max_seconds: int | None = Form(None), file: UploadFile | None = File(None)):
        if not url and not file:
            raise HTTPException(400, "lien ou fichier requis")
        jid = eng.db.add_job("import", url or (file.filename if file else ""))
        path = None
        if file:
            d = data / "imports" / str(jid)
            d.mkdir(parents=True, exist_ok=True)
            path = d / ("upload" + Path(file.filename or "x.mp4").suffix)
            with path.open("wb") as f:
                shutil.copyfileobj(file.file, f)
        clip_opts = {k: v for k, v in (("min_seconds", min_seconds), ("max_seconds", max_seconds)) if v}
        bg(eng.import_video(jid, path, url, {"streamer": streamer, "max_clips": max_clips, "clip": clip_opts}))
        return {"job": jid}

    @app.post("/api/compilations")
    async def compilation(clip_ids: list[int] | None = Body(None), streamer: str | None = Body(None),
                          hours: float | None = Body(None), count: int | None = Body(None),
                          title: str = Body(""), transition: str | None = Body(None),
                          duration: float | None = Body(None), max_each: float | None = Body(None),
                          effect: str = Body("none"), intro_text: bool = Body(True),
                          pick: str | None = Body(None)):
        c = eng.db.settings()["compilation"]
        if not clip_ids:  # résumé automatique : meilleurs moments récents
            clip_ids = eng.best_clips(streamer, hours or c["hours"], count or c["clips"], pick or "recent")
        if len(clip_ids) < 2:
            raise HTTPException(400, "pas assez de clips (il en faut au moins 2)")
        tr = transition or c["transition"]
        if tr not in TRANSITIONS:
            raise HTTPException(400, "transition inconnue")
        title = title or (f"Le best-of de {streamer} 🔥" if streamer else "Best-of du live 🔥")
        jid = eng.db.add_job("compilation", f"{title} ({len(clip_ids)} clips)")
        bg(eng.build_compilation(jid, clip_ids, title, tr, duration or c["transition_duration"],
                                 max_each if max_each is not None else c["max_each"], effect, intro_text))
        return {"job": jid, "clips": clip_ids}

    # ------------------------------------------------------------ médias (calques de la timeline)
    from . import overlays as ovl
    assets = data / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    @app.get("/api/assets")
    async def list_assets():
        from . import clipper
        out = []
        for p in sorted(assets.iterdir(), key=lambda x: -x.stat().st_mtime):
            kind = ovl.asset_kind(p.name)
            if not p.is_file() or not kind:
                continue
            dur = None
            if kind in ("video", "audio"):
                try:
                    dur = await clipper.probe_duration(p)
                except Exception:
                    dur = None
            out.append({"name": p.name, "kind": kind, "size": p.stat().st_size, "duration": dur})
        return out

    @app.post("/api/assets")
    async def upload_asset(file: UploadFile = File(...)):
        import re as _re
        name = _re.sub(r"[^\w.\-]", "_", Path(file.filename or "media").name)[-80:]
        if not ovl.asset_kind(name):
            raise HTTPException(400, "format non pris en charge (image, vidéo ou son)")
        dst = assets / name
        i = 1
        while dst.exists():
            dst = assets / f"{Path(name).stem}_{i}{Path(name).suffix}"
            i += 1
        with dst.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        return {"name": dst.name, "kind": ovl.asset_kind(dst.name)}

    @app.delete("/api/assets/{name}")
    def delete_asset(name: str):
        p = assets / Path(name).name
        if p.is_file():
            p.unlink()
        return {"ok": True}

    @app.get("/api/sounds/search")
    async def sound_search(q: str, kind: str = "sfx", page: int = 1):
        from . import sounds
        try:
            return await sounds.search(q[:80], kind, page)
        except Exception as e:
            raise HTTPException(502, str(e))

    @app.post("/api/sounds/import")
    async def sound_import(item: dict = Body(...)):
        from . import sounds
        if not str(item.get("url", "")).startswith("https://"):
            raise HTTPException(400, "lien invalide")
        try:
            name = await sounds.download(item, assets)
        except Exception as e:
            raise HTTPException(502, f"téléchargement impossible : {e}")
        return {"name": name, "kind": "audio"}

    @app.get("/api/emoji")
    def emoji(c: str):
        if not c or len(c) > 16:
            raise HTTPException(400)
        return FileResponse(ovl.emoji_png(c, data), media_type="image/png")

    @app.get("/api/jobs")
    def jobs():
        return eng.db.jobs()

    @app.exception_handler(RuntimeError)
    async def rt(_req, exc):
        return JSONResponse({"detail": str(exc)}, status_code=500)

    app.mount("/fonts", StaticFiles(directory=ROOT / "fonts"), name="fonts")
    app.mount("/sfx", StaticFiles(directory=ROOT / "sfx"), name="sfx")
    app.mount("/assets", StaticFiles(directory=data / "assets"), name="assets")
    app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
    return app
