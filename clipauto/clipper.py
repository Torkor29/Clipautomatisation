"""Extraction de la source, transcription mot à mot, découpe intelligente et rendu final 9:16."""
from __future__ import annotations

import asyncio
import re
import logging
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np

from .captions import build_ass, full_style, sfx_times
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


STOP = {
    "fr": {"le", "la", "les", "de", "des", "du", "et", "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "est",
           "c'est", "pas", "que", "qui", "un", "une", "en", "dans", "ce", "ça", "sur", "pour", "mais", "ou", "mon",
           "ma", "mes", "ton", "ta", "là", "oui", "non", "quoi", "avec", "j'ai", "y", "frère", "vous", "les", "wesh",
           "putain", "bah", "genre", "trop", "fait", "faut", "va", "vas", "suis", "es", "était", "moi", "toi"},
    "en": {"the", "you", "i", "is", "are", "to", "and", "of", "a", "it", "that", "what", "this", "my", "your", "me",
           "we", "they", "he", "she", "do", "don't", "i'm", "you're", "it's", "for", "on", "in", "with", "have",
           "get", "got", "just", "not", "yeah", "yes", "okay", "man", "let's", "can", "will", "was", "be", "please",
           "little", "bit", "stop", "gonna", "wanna", "right", "now", "come", "here", "look", "know", "think",
           "maybe", "how", "much", "who", "where", "why", "there", "like", "want", "need", "fucking", "shit"},
    "es": {"el", "la", "los", "las", "de", "que", "y", "en", "un", "una", "es", "no", "por", "con", "para", "lo",
           "yo", "tú", "pero", "qué", "está", "muy", "como", "más", "hermano"},
}


def guess_lang(text: str) -> tuple[str | None, int]:
    """Langue d'une phrase d'après ses mots-outils (gratuit, instantané). Renvoie (langue, avance)."""
    toks = re.findall(r"[\w'’]+", text.lower().replace("’", "'"))
    if len(toks) < 2:
        return None, 0
    scores = sorted(((sum(t in st for t in toks), lg) for lg, st in STOP.items()), reverse=True)
    (best, lg), (second, _) = scores[0], scores[1]
    return (lg, best - second) if best > second else (None, 0)


def transcribe(path: Path, model_size: str = "small", language: str | None = None,
               streamer_only: bool = True) -> list[dict]:
    """Mots avec horodatage précis (faster-whisper word_timestamps + VAD).

    `streamer_only` : la langue est détectée PHRASE PAR PHRASE ; les phrases dans une autre
    langue que celle du streamer (voix des PNJ du jeu, vidéo regardée…) sont marquées
    `skip` : gardées dans la transcription mais jamais affichées en sous-titres."""
    audio = load_pcm(path)
    filt = bool(streamer_only and language)
    if filt and model_size in ("tiny", "base"):  # trop petits pour distinguer les langues phrase par phrase
        model_size = "small"
    segs, _ = _model(model_size).transcribe(audio, word_timestamps=True, vad_filter=True,
                                            language=None if filt else (language or None),
                                            multilingual=filt, beam_size=5,
                                            condition_on_previous_text=False)
    words = []
    model = _model(model_size)
    for s in segs:
        skip, lg = False, None
        if filt:
            # 1) langue entendue dans le SON de la phrase (fiable même si Whisper a « traduit »)
            try:
                chunk = audio[int(s.start * 16000):int(s.end * 16000)]
                if len(chunk) > 16000 * 0.6:
                    _, _, probs = model.detect_language(audio=chunk)
                    pr = dict(probs)
                    top, ptop = max(pr.items(), key=lambda x: x[1])
                    if top != language and ptop >= 0.55 and pr.get(language, 0) < 0.25:
                        skip, lg = True, top
            except Exception:  # la détection ne doit jamais bloquer la transcription
                pass
            # 2) mots-outils du texte (rattrape les phrases courtes)
            if not skip:
                g, lead = guess_lang(s.text)
                if g and g != language and lead >= 1:
                    skip, lg = True, g
        for w in s.words or []:
            if w.word.strip():
                d = {"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3)}
                if skip:
                    d["skip"] = True
                    d["lang"] = lg
                words.append(d)
    # « qu » + « 'il » → « qu'il » ; « peut » + « -être » → « peut-être »
    merged: list[dict] = []
    for w in words:
        if merged and (w["w"][:1] in "'’-" or merged[-1]["w"][-1:] in "'’"):
            merged[-1] = {**merged[-1], "w": merged[-1]["w"] + w["w"], "e": w["e"]}
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


TRANSITIONS = {  # nom affiché → filtre xfade (« cut » = coupe sèche)
    "cut": "Coupe sèche", "fade": "Fondu enchaîné", "fadeblack": "Fondu au noir", "fadewhite": "Flash blanc",
    "dissolve": "Dissolution", "slideleft": "Glisser ←", "slideright": "Glisser →", "slideup": "Glisser ↑",
    "slidedown": "Glisser ↓", "wipeleft": "Volet ←", "wiperight": "Volet →", "smoothleft": "Balayage doux",
    "circleopen": "Cercle", "radial": "Radial", "zoomin": "Zoom", "pixelize": "Pixels", "hblur": "Flou",
    "squeezev": "Écrasement",
}
EFFECTS = {"none": "Aucun", "zoomin": "Zoom progressif", "punch": "Zoom fixe (punch-in)",
           "zoomout": "Dézoom", "bw": "Noir & blanc", "slowmo": "Ralenti ×0.75", "fast": "Accéléré ×1.25"}


def segments_of(edit: dict) -> list[dict]:
    segs = edit.get("segments") or [{"s": edit["trim"][0], "e": edit["trim"][1]}]
    return [x for x in segs if x["e"] - x["s"] > 0.2]


def seg_speed(seg: dict, global_speed: float = 1.0) -> float:
    fx = seg.get("effect", "none")
    return global_speed * (0.75 if fx == "slowmo" else 1.25 if fx == "fast" else 1.0)


def timeline(edit: dict) -> list[dict]:
    """Position de chaque segment dans la vidéo finale (en tenant compte des transitions et vitesses)."""
    out, t, sp = [], 0.0, float(edit.get("speed", 1.0) or 1.0)
    for i, seg in enumerate(segments_of(edit)):
        d = (seg["e"] - seg["s"]) / seg_speed(seg, sp)
        tr = seg.get("transition") or {}
        td = 0.0 if i == 0 or tr.get("type", "cut") == "cut" else min(float(tr.get("duration", 0.4)), d / 2)
        start = t - td
        out.append({**seg, "out_start": start, "out_dur": d, "td": td})
        t = start + d
    return out


def output_duration(edit: dict) -> float:
    tl = timeline(edit)
    return tl[-1]["out_start"] + tl[-1]["out_dur"] if tl else 0.0


def remap_words(words: list[dict], edit: dict) -> list[dict]:
    """Mots de la source → temps de la vidéo finale (pour les sous-titres)."""
    out = []
    tl = timeline(edit)
    sp = float(edit.get("speed", 1.0) or 1.0)
    for k, seg in enumerate(tl):
        f = seg_speed(seg, sp)
        lo = seg["s"] + (seg["td"] * f if k else 0)  # pendant la transition : sous-titres du segment précédent
        for w in words:
            if w["s"] >= lo - 0.01 and w["s"] < seg["e"]:
                out.append({**w, "s": seg["out_start"] + (w["s"] - seg["s"]) / f,
                            "e": seg["out_start"] + (min(w["e"], seg["e"]) - seg["s"]) / f})
    return out


def layout_filter(layout: dict, iw: int, ih: int, inp: str = "0:v", outl: str = "v") -> str:
    mode = layout.get("mode", "blur")
    if mode == "fill":
        fx = float(layout.get("focus", {}).get("x", 0.5))
        nw = ih * 9 / 16
        x = min(max(fx * iw - nw / 2, 0), iw - nw)
        return f"[{inp}]crop={int(nw) // 2 * 2}:{ih}:{int(x)}:0,scale={OUT_W}:{OUT_H},setsar=1[{outl}]"
    if mode == "split":
        r = float(layout.get("split_ratio", 0.42))
        th = int(OUT_H * r) // 2 * 2
        bh = OUT_H - th
        top = _crop(layout.get("facecam", {}), iw, ih, OUT_W / th)
        bot = _crop(layout.get("gameplay", {}), iw, ih, OUT_W / bh)
        if layout.get("cam_position", "top") == "bottom":  # jeu en haut, cam en bas
            top = _crop(layout.get("facecam", {}), iw, ih, OUT_W / bh)
            bot = _crop(layout.get("gameplay", {}), iw, ih, OUT_W / th)
            return (f"[{inp}]split[{outl}a][{outl}b];[{outl}a]{top},scale={OUT_W}:{bh}[{outl}t];"
                    f"[{outl}b]{bot},scale={OUT_W}:{th}[{outl}g];[{outl}g][{outl}t]vstack,setsar=1[{outl}]")
        return (f"[{inp}]split[{outl}a][{outl}b];[{outl}a]{top},scale={OUT_W}:{th}[{outl}t];[{outl}b]{bot},scale={OUT_W}:{bh}[{outl}g];"
                f"[{outl}t][{outl}g]vstack,setsar=1[{outl}]")
    if mode == "pip":  # jeu plein écran + cam incrustée dans un coin
        size = float(layout.get("pip_size", 0.42))
        cw = int(OUT_W * size) // 2 * 2
        fc = layout.get("facecam", {})
        ch = int(cw * (fc.get("h", .3) * ih) / max(fc.get("w", .3) * iw, 1)) // 2 * 2
        ch = min(max(ch, 2), OUT_H // 2 // 2 * 2)
        game = _crop(layout.get("gameplay", {}), iw, ih, OUT_W / OUT_H)
        cam = _crop(fc, iw, ih, cw / ch)
        corner = layout.get("pip_corner", "tl")
        m = 40
        x = m if corner in ("tl", "bl") else f"W-w-{m}"
        y = 220 if corner in ("tl", "tr") else f"H-h-{m + 200}"
        return (f"[{inp}]split[{outl}a][{outl}b];[{outl}a]{game},scale={OUT_W}:{OUT_H}[{outl}g];"
                f"[{outl}b]{cam},scale={cw}:{ch},pad={cw + 12}:{ch + 12}:6:6:white[{outl}c];"
                f"[{outl}g][{outl}c]overlay={x}:{y},setsar=1[{outl}]")
    if mode == "fit":
        return (f"[{inp}]scale={OUT_W}:-2,pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[{outl}]")
    # blur : vidéo entière au centre + fond flouté
    zoom = float(layout.get("zoom", 1.0))
    return (f"[{inp}]split[{outl}a][{outl}b];[{outl}a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{OUT_H},boxblur=30:3,eq=brightness=-0.08[{outl}bg];"
            f"[{outl}b]scale={int(OUT_W * zoom) // 2 * 2}:-2[{outl}fg];[{outl}bg][{outl}fg]overlay=(W-w)/2:(H-h)/2,setsar=1[{outl}]")


def effect_filter(fx: str, d: float) -> str:
    if fx == "zoomin":
        return (f",zoompan=z='min(1+0.15*on/{max(int(d * 30), 1)},1.15)':d=1:x='iw/2-iw/zoom/2':"
                f"y='ih/2-ih/zoom/2':s={OUT_W}x{OUT_H}:fps=30")
    if fx == "zoomout":
        return (f",zoompan=z='max(1.15-0.15*on/{max(int(d * 30), 1)},1)':d=1:x='iw/2-iw/zoom/2':"
                f"y='ih/2-ih/zoom/2':s={OUT_W}x{OUT_H}:fps=30")
    if fx == "punch":
        return f",scale={int(OUT_W * 1.18) // 2 * 2}:-2,crop={OUT_W}:{OUT_H}"
    if fx == "bw":
        return ",hue=s=0"
    return ""


async def has_audio(path: Path) -> bool:
    out = await run("ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                    "-of", "csv=p=0", str(path))
    return bool(out.strip())


async def render(source: Path, words: list[dict], edit: dict, out: Path, keywords: list[str] | None = None,
                 data_dir: Path | None = None) -> Path:
    """Rendu 9:16 : segments (découpes multiples) + effets + transitions xfade + sous-titres karaoké."""
    iw, ih = await probe_size(source)
    audio = await has_audio(source)
    tl = timeline(edit)
    sp = float(edit.get("speed", 1.0) or 1.0)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        ass = Path(td) / "subs.ass"
        total = output_duration(edit)
        rwords = remap_words(words, edit) if edit.get("captions", True) else []
        sfx_wav = None
        st = full_style(edit["style"])
        if audio and rwords and st.get("sfx", "none") != "none":
            ts = sfx_times(rwords, st, keywords)
            if ts:
                sfx_wav = Path(td) / "sfx.wav"
                await asyncio.to_thread(_sfx_track, st["sfx"], ts, total, float(st.get("sfx_volume", 35)) / 100, sfx_wav)
        from . import overlays as ovl
        items = ovl.clean(edit.get("overlays"))
        ass_txt = build_ass(rwords, edit["style"], offset=0, duration=total, hook=edit.get("hook"),
                            hook_text=edit.get("title", ""), layout=edit.get("layout"), keywords=keywords)
        ass_txt += "\n".join(ovl.text_events(items, total)) + "\n"
        ass.write_text(ass_txt, encoding="utf-8")
        parts = []
        for i, seg in enumerate(tl):
            f = seg_speed(seg, sp)
            parts.append(f"[0:v]trim={seg['s']:.3f}:{seg['e']:.3f},setpts=PTS-STARTPTS[r{i}]")
            parts.append(layout_filter(edit.get("layout", {}), iw, ih, f"r{i}", f"l{i}"))
            parts.append(f"[l{i}]fps=30{effect_filter(seg.get('effect', 'none'), seg['out_dur'])},"
                         f"setpts=PTS/{f:.4f},fps=30,scale={OUT_W}:{OUT_H},setsar=1,format=yuv420p,settb=AVTB[v{i}]")
            if audio:
                at = f"atempo={f:.4f}," if abs(f - 1) > 1e-3 else ""
                parts.append(f"[0:a]atrim={seg['s']:.3f}:{seg['e']:.3f},asetpts=PTS-STARTPTS,{at}"
                             f"aresample=48000,aformat=channel_layouts=stereo[a{i}]")
        vcur, acur = "v0", "a0"
        for i in range(1, len(tl)):
            seg, tr = tl[i], (tl[i].get("transition") or {})
            if seg["td"] > 0:
                parts.append(f"[{vcur}][v{i}]xfade=transition={tr.get('type', 'fade')}:duration={seg['td']:.3f}:"
                             f"offset={seg['out_start']:.3f}[vx{i}]")
                if audio:
                    parts.append(f"[{acur}][a{i}]acrossfade=d={seg['td']:.3f}[ax{i}]")
            else:
                parts.append(f"[{vcur}][v{i}]concat=n=2:v=1:a=0[vx{i}]")
                if audio:
                    parts.append(f"[{acur}][a{i}]concat=n=2:v=0:a=1[ax{i}]")
            vcur, acur = f"vx{i}", f"ax{i}"
        extra = []
        if sfx_wav:
            extra = ["-i", str(sfx_wav)]
            parts.append(f"[{acur}][1:a]amix=inputs=2:duration=first:normalize=0[amx]")
            acur = "amx"
        # calques de la timeline : images / emojis / vidéos, puis textes (libass) par-dessus
        ddir = data_dir or source.parent.parent.parent
        vargs, vparts, vcur, vaudio = ovl.visual_chain(items, ddir, SFX_DIR, 1 + len(extra) // 2, vcur, total)
        extra += vargs
        parts += vparts
        aargs, aaudio = ovl.audio_inputs(items, ddir, SFX_DIR, 1 + len([a for a in extra if a == "-i"]))
        extra += aargs
        parts.append(f"[{vcur}]ass={ass}:fontsdir={FONTS_DIR}[out]")
        if vaudio or aaudio:
            mparts, acur = ovl.audio_mix(acur if audio else None, vaudio + aaudio, total)
            parts += mparts
            audio = True
        amap = ["-map", f"[{acur}]"] if audio else []
        await run("ffmpeg", "-loglevel", "error", "-y", "-i", str(source), *extra, "-filter_complex", ";".join(parts),
                  "-map", "[out]", *amap, "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "faster", "-crf", "20",
                  "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                  str(out))
    log.info("rendu: %s", out)
    return out


SFX_DIR = Path(__file__).resolve().parent.parent / "sfx"


def _sfx_track(name: str, times: list[float], total: float, vol: float, out: Path) -> None:
    """Piste de bruitages (48 kHz stéréo) : le son `name` posé à chaque instant de `times`."""
    import wave
    src = SFX_DIR / f"{name}.mp3"
    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(src), "-ac", "2", "-ar", "48000", "-f", "s16le",
                          "pipe:1"], capture_output=True, check=True).stdout
    clip = np.frombuffer(pcm, np.int16).reshape(-1, 2).astype(np.float32) * vol
    n = int((total + 1) * 48000)
    track = np.zeros((n, 2), np.float32)
    for t in times:
        i = int(t * 48000)
        if 0 <= i < n:
            j = min(n, i + len(clip))
            track[i:j] += clip[: j - i]
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.clip(track, -32768, 32767).astype(np.int16).tobytes())


async def normalize_part(src: Path, t0: float, t1: float, out: Path) -> Path:
    """Morceau 1920x1080 30 fps homogène (pour assembler des clips de sources différentes)."""
    await run("ffmpeg", "-loglevel", "error", "-y", "-ss", f"{max(t0, 0):.3f}", "-i", str(src), "-t", f"{t1 - t0:.3f}",
              "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1",
              "-af", "aresample=48000", "-ac", "2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
              "-c:a", "aac", "-b:a", "192k", str(out))
    return out


async def concat_parts(parts: list[Path], out: Path) -> Path:
    lst = out.parent / "parts.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    await run("ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
              "-movflags", "+faststart", str(out))
    lst.unlink(missing_ok=True)
    return out
