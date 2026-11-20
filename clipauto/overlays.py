"""Calques de la timeline multi-pistes (façon CapCut) : textes, images/stickers, emojis, vidéos, sons.

Un calque = {"id", "type": text|image|emoji|video|audio, "track", "start", "end"} en secondes de la
vidéo FINALE, + ses propriétés. Les positions x / y sont le CENTRE en fractions (0-1) de l'écran
1080x1920, la largeur `w` en fraction de 1080.

Rendu : images / vidéos par `overlay` ffmpeg, textes par libass (même moteur que les sous-titres),
sons mixés (avec « ducking » : la musique baisse quand le streamer parle).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .captions import FONT_FILES, _c, _esc, _rrect, _t, em_ratio, text_width

W, H = 1080, 1920
ROOT = Path(__file__).resolve().parent.parent
EMOJI_FONT = Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf")
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VID_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
AUD_EXT = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}


def asset_kind(name: str) -> str | None:
    ext = Path(name).suffix.lower()
    return "image" if ext in IMG_EXT else "video" if ext in VID_EXT else "audio" if ext in AUD_EXT else None


def emoji_png(char: str, data_dir: Path) -> Path:
    """Emoji en couleur → PNG transparent (libass ne sait pas afficher les emojis couleur)."""
    out = data_dir / "assets" / "emoji" / (hashlib.md5(char.encode()).hexdigest()[:12] + ".png")
    if out.exists():
        return out
    from PIL import Image, ImageDraw, ImageFont
    out.parent.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(EMOJI_FONT), 109)  # Noto Color Emoji n'existe qu'en taille 109
    im = Image.new("RGBA", (180, 160), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((10, 10), char, font=font, embedded_color=True)
    bbox = im.getbbox() or (0, 0, 180, 160)
    im.crop(bbox).resize((256, int(256 * (bbox[3] - bbox[1]) / max(bbox[2] - bbox[0], 1))), Image.LANCZOS).save(out)
    return out


def resolve(item: dict, data_dir: Path, sfx_dir: Path) -> Path | None:
    src = item.get("src", "")
    if item["type"] == "emoji":
        return emoji_png(item.get("emoji", "😂"), data_dir)
    if src.startswith("sfx:"):
        p = sfx_dir / f"{src[4:]}.mp3"
    elif src.startswith("asset:"):
        p = data_dir / "assets" / Path(src[6:]).name
    else:
        return None
    return p if p.exists() else None


# ------------------------------------------------------------------ textes (ASS)
ANIM_IN = {"none": "Aucune", "pop": "Pop", "fade": "Fondu", "slide_up": "Glisse ↑", "slide_left": "Glisse ←",
           "typewriter": "Machine à écrire"}


def text_events(items: list[dict], total: float) -> list[str]:
    ev = []
    for it in sorted((i for i in items if i["type"] == "text"), key=lambda i: i.get("track", 0)):
        s, e = max(float(it["start"]), 0), min(float(it["end"]), total)
        if e - s < 0.05 or not it.get("text", "").strip():
            continue
        font = it.get("font", "Montserrat Black")
        size = int(it.get("size", 80))
        x, y = float(it.get("x", .5)) * W, float(it.get("y", .2)) * H
        lines = it["text"].upper().split("\n") if it.get("uppercase") else it["text"].split("\n")
        ol = int(it.get("outline", 6))
        layer = 10 + int(it.get("track", 0)) * 2
        tags = (f"\\an5\\fn{font}\\fs{size}\\c{_c(it.get('color', '#FFFFFF'))}\\3c{_c(it.get('outline_color', '#000000'))}"
                f"\\bord{ol}\\shad{int(it.get('shadow', 2))}\\b0")
        if it.get("rotation"):
            tags += f"\\frz{-float(it['rotation']):.1f}"
        a_in, a_out = it.get("anim_in", "pop"), it.get("anim_out", "fade")
        move = f"\\pos({x:.0f},{y:.0f})"
        anim = ""
        if a_in == "pop":
            anim += r"\fscx40\fscy40\t(0,140,\fscx112\fscy112)\t(140,240,\fscx100\fscy100)"
        elif a_in == "fade":
            anim += r"\alpha&HFF&\t(0,250,\alpha&H00&)"
        elif a_in == "slide_up":
            move = f"\\move({x:.0f},{y + 120:.0f},{x:.0f},{y:.0f},0,260)"
        elif a_in == "slide_left":
            move = f"\\move({x + 300:.0f},{y:.0f},{x:.0f},{y:.0f},0,260)"
        if a_out == "fade":
            anim += r"\fad(0,200)" if a_in != "fade" else ""
        # fond (boîte arrondie) derrière le texte
        if it.get("bg"):
            px = size * em_ratio(font) if font in FONT_FILES else size * .7
            tw = max(text_width(l, font, size) for l in lines) if font in FONT_FILES else max(len(l) for l in lines) * px * .6
            th = px * 1.25 * len(lines)
            pad = px * .35
            alpha = int(255 * (1 - float(it.get("bg_opacity", 100)) / 100))
            fad = r"\fad(150,200)"
            ev.append(f"Dialogue: {layer},{_t(s)},{_t(e)},Box,,0,0,0,,{{\\an7\\pos(0,0)\\1c{_c(it['bg'])}\\1a&H{alpha:02X}&{fad}\\p1}}"
                      f"{_rrect(x - tw / 2 - pad, y - th / 2 - pad * .6, x + tw / 2 + pad, y + th / 2 + pad * .6, px * .3)}{{\\p0}}")
        if a_in == "typewriter":  # les lettres apparaissent une à une
            txt = "\\N".join(lines)
            n = max(len(txt), 1)
            step = min(0.05, max((e - s) * 0.4 / n, 0.015))
            k = "".join(f"{{\\alpha&HFF&\\t({int(i * step * 1000)},{int(i * step * 1000) + 1},\\alpha&H00&)}}{_esc(ch)}"
                        if ch != "\\" else ch for i, ch in enumerate(txt))
            ev.append(f"Dialogue: {layer + 1},{_t(s)},{_t(e)},Cap,,0,0,0,,{{{tags}{move}}}{k}")
        else:
            ev.append(f"Dialogue: {layer + 1},{_t(s)},{_t(e)},Cap,,0,0,0,,{{{tags}{move}{anim}}}"
                      + "\\N".join(_esc(l) for l in lines))
    return ev


# ------------------------------------------------------------------ images, emojis, vidéos (ffmpeg)
def visual_chain(items: list[dict], data_dir: Path, sfx_dir: Path, first_input: int, vcur: str,
                 total: float) -> tuple[list[str], list[str], str, list[tuple[str, dict]]]:
    """Renvoie (arguments -i, filtres, label vidéo final, [(label audio, calque)] pour le mix)."""
    args, parts, audio_labels = [], [], []
    n = first_input
    vis = sorted((i for i in items if i["type"] in ("image", "emoji", "video")), key=lambda i: i.get("track", 0))
    for k, it in enumerate(vis):
        p = resolve(it, data_dir, sfx_dir)
        if not p:
            continue
        s, e = max(float(it["start"]), 0), min(float(it["end"]), total)
        if e - s < 0.05:
            continue
        w = max(int(float(it.get("w", .4)) * W) // 2 * 2, 2)
        is_vid = it["type"] == "video"
        if is_vid:
            args += ["-i", str(p)]
            ti = float(it.get("trim_in", 0))
            chain = f"[{n}:v]trim=start={ti:.3f}:duration={e - s:.3f},setpts=PTS-STARTPTS+{s:.3f}/TB,scale={w}:-2"
        elif p.suffix.lower() == ".gif":
            args += ["-ignore_loop", "0", "-i", str(p)]
            chain = f"[{n}:v]trim=duration={e:.3f},setpts=PTS-STARTPTS,scale={w}:-2"
        else:
            args += ["-loop", "1", "-t", f"{e:.3f}", "-framerate", "30", "-i", str(p)]
            chain = f"[{n}:v]scale={w}:-2"
        chain += ",format=rgba"
        if it.get("rotation"):
            r = float(it["rotation"]) * 3.14159265 / 180
            chain += f",rotate={r:.4f}:c=none:ow=rotw({r:.4f}):oh=roth({r:.4f})"
        if it.get("opacity", 100) < 100:
            chain += f",colorchannelmixer=aa={float(it['opacity']) / 100:.2f}"
        a_in, a_out = it.get("anim_in", "pop"), it.get("anim_out", "fade")
        if a_in in ("fade", "pop"):
            chain += f",fade=t=in:st={s:.3f}:d={0.18 if a_in == 'pop' else 0.3}:alpha=1"
        if a_out == "fade":
            chain += f",fade=t=out:st={max(e - 0.25, s):.3f}:d=0.25:alpha=1"
        parts.append(chain + f"[ov{k}]")
        x, y = float(it.get("x", .5)) * W, float(it.get("y", .5)) * H
        xe, ye = f"{x:.0f}-w/2", f"{y:.0f}-h/2"
        if a_in == "slide_up":
            ye = f"{y:.0f}-h/2+max(0\\,1-(t-{s:.3f})/0.3)*200"
        elif a_in == "slide_left":
            xe = f"{x:.0f}-w/2+max(0\\,1-(t-{s:.3f})/0.3)*400"
        elif a_in == "pop":  # petit rebond vertical
            ye = f"{y:.0f}-h/2+max(0\\,1-(t-{s:.3f})/0.18)*40"
        parts.append(f"[{vcur}][ov{k}]overlay=x='{xe}':y='{ye}':enable='between(t,{s:.3f},{e:.3f})':"
                     f"eof_action=pass[vo{k}]")
        vcur = f"vo{k}"
        if is_vid and not it.get("muted", False):
            audio_labels.append((f"{n}:a", it))
        n += 1
    return args, parts, vcur, audio_labels


def audio_inputs(items: list[dict], data_dir: Path, sfx_dir: Path, first_input: int) -> tuple[list[str], list[tuple[str, dict]]]:
    args, labels = [], []
    n = first_input
    for it in (i for i in items if i["type"] == "audio"):
        p = resolve(it, data_dir, sfx_dir)
        if not p:
            continue
        args += ["-i", str(p)]
        labels.append((f"{n}:a", it))
        n += 1
    return args, labels


def audio_mix(main: str | None, labels: list[tuple[str, dict]], total: float) -> tuple[list[str], str]:
    """Mixe la voix + les sons des calques. Musique avec « ducking » : elle baisse quand ça parle."""
    parts, ins = [], []
    labels = [(lab, it) for lab, it in labels
              if min(float(it["end"]), total) - max(float(it["start"]), 0) >= 0.05]
    if main is None:
        parts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[abase]")
        main = "abase"
    ducks = [it for _, it in labels if it.get("duck")]
    if ducks:
        parts.append(f"[{main}]asplit={len(ducks) + 1}[amain]" + "".join(f"[sc{i}]" for i in range(len(ducks))))
        main = "amain"
    ins.append(f"[{main}]")
    di = 0
    for k, (lab, it) in enumerate(labels):
        s, e = max(float(it["start"]), 0), min(float(it["end"]), total)
        if e - s < 0.05:
            continue
        ti = float(it.get("trim_in", 0))
        vol = float(it.get("volume", 100)) / 100
        ms = int(s * 1000)
        ch = (f"[{lab}]atrim=start={ti:.3f}:duration={e - s:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
              f"aformat=channel_layouts=stereo,volume={vol:.2f}")
        if it.get("fade_in"):
            ch += f",afade=t=in:d={float(it['fade_in']):.2f}"
        if it.get("fade_out"):
            ch += f",afade=t=out:st={max(e - s - float(it['fade_out']), 0):.2f}:d={float(it['fade_out']):.2f}"
        ch += f",adelay={ms}|{ms}[au{k}]"
        parts.append(ch)
        lab_out = f"au{k}"
        if it.get("duck"):
            parts.append(f"[au{k}][sc{di}]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=450[aud{k}]")
            lab_out = f"aud{k}"
            di += 1
        ins.append(f"[{lab_out}]")
    if len(ins) == 1:
        return parts, main
    parts.append("".join(ins) + f"amix=inputs={len(ins)}:duration=first:normalize=0[amixo]")
    return parts, "amixo"


def clean(items: list[dict]) -> list[dict]:
    """Validation légère (les calques viennent du navigateur)."""
    out = []
    for it in items or []:
        if it.get("type") not in ("text", "image", "emoji", "video", "audio"):
            continue
        try:
            s, e = float(it["start"]), float(it["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if e > s:
            src = str(it.get("src", ""))
            if src and not re.match(r"^(asset|sfx):[\w.\-]+$", src):
                continue
            out.append(it)
    return out
