"""Sous-titres animés style TikTok / CapCut (moteur ASS « mot par mot »).

Chaque mot est placé individuellement (mesure de la police avec Pillow) : ça permet des
animations par mot (pop, zoom, rebond, apparition progressive), des entrées de ligne
(fondu, glissé, zoom), une boîte derrière le mot actif, un halo lumineux, des mots
importants en couleur et des bruitages synchronisés.

Inspiré des modèles du projet open source pycaps (MIT) — réimplémenté pour libass.
L'aperçu web (web/app.js → capLayout / capState) applique les mêmes règles.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .virality import EMOTION, FILLERS

ROOT = Path(__file__).resolve().parent.parent
FONT_FILES = {  # nom affiché → fichier
    "Montserrat Black": "fonts/Montserrat-Black.ttf",
    "Montserrat ExtraBold": "fonts/Montserrat-ExtraBold.ttf",
    "Poppins Black": "fonts/Poppins-Black.ttf",
    "Poppins ExtraBold": "fonts/Poppins-ExtraBold.ttf",
    "Anton": "fonts/Anton-Regular.ttf",
    "Bangers": "fonts/Bangers-Regular.ttf",
    "Bebas Neue": "fonts/BebasNeue-Regular.ttf",
}
FONTS = {k: (k, 0) for k in FONT_FILES}

BASE = {
    "font": "Montserrat Black", "size": 100, "uppercase": True, "color": "#FFFFFF", "pending_color": "#FFFFFF",
    "highlight": "#FFE500", "highlight_mode": "color", "highlight_text": "#000000",
    "emphasis": True, "emphasis_color": "#FF4D4D", "outline_color": "#000000", "outline": 7, "shadow": 3,
    "glow": False, "glow_color": "#FF8800", "box": False, "box_color": "#000000", "box_opacity": 70,
    "words_per_line": 3, "max_chars": 18, "word_anim": "pop", "line_in": "none", "line_out": "none",
    "reveal": "all", "sfx": "none", "sfx_on": "line", "sfx_volume": 35,
}

# Modèles (« templates ») : chacun = style complet. Clé = id, "label" = nom affiché.
PRESETS = {
    "karaoke": {"label": "Karaoké", "highlight": "#FFE500", "word_anim": "pop"},
    "hormozi": {"label": "Hormozi", "highlight": "#2BFF55", "emphasis_color": "#FFE500", "words_per_line": 2,
                "size": 112, "outline": 8, "shadow": 4, "word_anim": "zoom"},
    "mrbeast": {"label": "MrBeast", "font": "Bangers", "highlight": "#FFE500", "emphasis_color": "#FF3B3B",
                "words_per_line": 2, "size": 128, "outline": 9, "shadow": 5, "word_anim": "bounce"},
    "boxed": {"label": "Mot encadré", "highlight_mode": "box", "highlight": "#8B5CF6", "highlight_text": "#FFFFFF",
              "word_anim": "pop", "outline": 5, "emphasis": False},
    "progressive": {"label": "Mot à mot", "reveal": "progressive", "word_anim": "zoom", "words_per_line": 4,
                    "highlight": "#FFFFFF", "max_chars": 24, "size": 92},
    "one_word": {"label": "Un seul mot", "words_per_line": 1, "size": 150, "word_anim": "pop",
                 "highlight": "#FFFFFF", "font": "Anton", "outline": 9},
    "explosive": {"label": "Explosif", "font": "Montserrat Black", "color": "#FFDD00", "pending_color": "#CCAA00",
                  "highlight": "#FFFFFF", "glow": True, "glow_color": "#FF5500", "word_anim": "zoom",
                  "line_in": "slide_left", "line_out": "fade", "sfx": "pop", "sfx_on": "emphasis"},
    "neon": {"label": "Néon", "font": "Poppins Black", "color": "#E0FFFF", "highlight": "#00F0FF", "glow": True,
             "glow_color": "#00B7FF", "outline": 2, "shadow": 0, "word_anim": "pop", "uppercase": False,
             "emphasis_color": "#FF2BD6"},
    "gaming": {"label": "Gaming", "font": "Anton", "highlight": "#00E5FF", "emphasis_color": "#FF2BD6",
               "size": 120, "word_anim": "bounce", "line_in": "slide_up", "line_out": "fade"},
    "line_box": {"label": "Ligne surlignée", "box": True, "box_color": "#2563EB", "box_opacity": 100,
                 "highlight": "#FFE500", "outline": 0, "shadow": 0, "word_anim": "none", "line_in": "zoom"},
    "classic": {"label": "Sous-titre classique", "font": "Poppins ExtraBold", "uppercase": False, "size": 80,
                "box": True, "box_opacity": 60, "outline": 0, "shadow": 0, "highlight": "#FFFFFF",
                "emphasis": False, "word_anim": "none", "words_per_line": 7, "max_chars": 32, "line_in": "fade"},
    "minimal": {"label": "Minimal", "font": "Poppins ExtraBold", "uppercase": False, "size": 84,
                "highlight": "#FFFFFF", "emphasis": False, "word_anim": "none", "words_per_line": 5,
                "max_chars": 26, "outline": 4, "shadow": 2, "line_in": "fade", "line_out": "fade"},
}
WORD_ANIMS = {"none": "Aucune", "pop": "Pop", "zoom": "Zoom (surgit)", "bounce": "Rebond"}
LINE_ANIMS = {"none": "Aucune", "fade": "Fondu", "slide_up": "Glisse vers le haut", "slide_left": "Glisse de droite",
              "zoom": "Zoom"}
SFX = {"none": "Aucun", "pop": "Pop", "pop-2": "Pop 2", "whoosh": "Whoosh", "swoosh": "Swoosh", "ding": "Ding",
       "ding-short": "Ding court", "click": "Clic", "hit-strong": "Impact", "glitch": "Glitch"}

W, H = 1080, 1920
_PUNCT = re.compile(r"[.,;:…«»\"“”()]+")


def full_style(style: dict) -> dict:
    return {**BASE, **(style or {})}


def ass_color(hex_color: str, alpha: int = 0) -> str:
    h = (hex_color or "#FFFFFF").lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _c(hex_color: str) -> str:  # couleur inline (\c&HBBGGRR&)
    h = (hex_color or "#FFFFFF").lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _t(sec: float) -> str:
    sec = max(sec, 0)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02}:{s:05.2f}"


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


@lru_cache(maxsize=32)
def _font(name: str, size: int):
    from PIL import ImageFont
    path = ROOT / FONT_FILES.get(name, "fonts/Montserrat-Black.ttf")
    return ImageFont.truetype(str(path), size)


@lru_cache(maxsize=32)
def em_ratio(font: str) -> float:
    """libass dimensionne la police pour que winAscent + winDescent (table OS/2) = taille ASS :
    la taille « réelle » du texte vaut taille × ce ratio (0,58 pour Anton, 0,64 Montserrat…)."""
    from fontTools.ttLib import TTFont
    t = TTFont(str(ROOT / FONT_FILES.get(font, "fonts/Montserrat-Black.ttf")), lazy=True)
    o = t["OS/2"]
    return t["head"].unitsPerEm / (o.usWinAscent + o.usWinDescent)


def text_width(text: str, font: str, size: int) -> float:
    return float(_font(font, max(int(round(size * em_ratio(font))), 1)).getlength(text))


def is_emphasis(word: str, keywords: set[str]) -> bool:
    w = re.sub(r"[^\w'’-]", "", word.lower())
    return bool(w) and (w in EMOTION or any(w.startswith(k) for k in keywords) or any(c.isdigit() for c in w))


def prepare_words(words: list[dict], style: dict, keywords: list[str] | None = None) -> list[dict]:
    """Nettoyage d'affichage. Les coupures de ligne se basent sur la ponctuation d'ORIGINE (champ `p`)."""
    kws = {k.lower().rstrip("*") for k in (keywords or []) if k}
    out = []
    for w in words:
        raw = w["w"].strip()
        base = re.sub(r"[^\w'’-]", "", raw.lower())
        if style.get("remove_fillers", True) and base in FILLERS:
            continue
        txt = _PUNCT.sub("", raw) if style.get("clean_punct", True) else raw
        if not txt.strip():
            continue
        out.append({**w, "w": txt, "p": raw[-1:] if raw[-1:] in ".?!,;:" else "",
                    "x": bool(style.get("emphasis", True) and is_emphasis(raw, kws))})
    return out


def group_words(words: list[dict], per_line: int, max_chars: int) -> list[list[dict]]:
    lines, cur = [], []
    for w in words:
        if not w.get("w", "").strip():
            continue
        if cur:
            gap = w["s"] - cur[-1]["e"]
            chars = sum(len(x["w"].strip()) + 1 for x in cur) + len(w["w"].strip())
            last_p = cur[-1].get("p", cur[-1]["w"].strip()[-1:])
            if len(cur) >= per_line or gap > 0.6 or chars > max_chars or (last_p and last_p in ".?!,"):
                lines.append(cur)
                cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def caption_y(style: dict, layout: dict | None) -> float:
    if style.get("auto_position", True) and layout and layout.get("mode") == "split":
        return float(layout.get("split_ratio", 0.5)) * 100
    return float(style.get("position", 72))


def layout_line(line: list[dict], st: dict, yc: float) -> list[dict]:
    """Position (centre x, y) de chaque mot ; retour à la ligne si trop large."""
    size, font = int(st["size"]), st["font"]
    up = st.get("uppercase", True)
    texts = [w["w"].upper() if up else w["w"] for w in line]
    widths = [text_width(t, font, size) for t in texts]
    # espace + marge pour l'animation « pop » (le mot actif grossit de ~15 %) et la boîte
    space = text_width(" ", font, size) + size * em_ratio(font) * (0.32 if st.get("highlight_mode") == "box" else 0.2)
    maxw = W * 0.86
    rows, cur, cw = [], [], 0.0
    for i, wd in enumerate(widths):
        add = wd if not cur else cw + space + wd
        if cur and add > maxw:
            rows.append(cur)
            cur, cw = [i], wd
        else:
            cur.append(i)
            cw = add
    if cur:
        rows.append(cur)
    row_h = size * em_ratio(font) * 1.25
    y0 = yc - (len(rows) - 1) * row_h / 2
    out = [None] * len(line)
    for r, idx in enumerate(rows):
        total = sum(widths[i] for i in idx) + space * (len(idx) - 1)
        x = W / 2 - total / 2
        for i in idx:
            out[i] = {"text": texts[i], "x": x + widths[i] / 2, "y": y0 + r * row_h, "w": widths[i], "row": r}
            x += widths[i] + space
    return out


def _rrect(x0, y0, x1, y1, r) -> str:
    """Dessin ASS d'un rectangle arrondi."""
    r = max(min(r, (x1 - x0) / 2, (y1 - y0) / 2), 0)
    k = r * 0.45
    return (f"m {x0 + r:.0f} {y0:.0f} l {x1 - r:.0f} {y0:.0f} b {x1 - k:.0f} {y0:.0f} {x1:.0f} {y0 + k:.0f} {x1:.0f} {y0 + r:.0f} "
            f"l {x1:.0f} {y1 - r:.0f} b {x1:.0f} {y1 - k:.0f} {x1 - k:.0f} {y1:.0f} {x1 - r:.0f} {y1:.0f} "
            f"l {x0 + r:.0f} {y1:.0f} b {x0 + k:.0f} {y1:.0f} {x0:.0f} {y1 - k:.0f} {x0:.0f} {y1 - r:.0f} "
            f"l {x0:.0f} {y0 + r:.0f} b {x0:.0f} {y0 + k:.0f} {x0 + k:.0f} {y0:.0f} {x0 + r:.0f} {y0:.0f}")


def build_ass(words: list[dict], style: dict, offset: float = 0.0, duration: float | None = None,
              hook: dict | None = None, hook_text: str = "", layout: dict | None = None,
              keywords: list[str] | None = None) -> str:
    st = full_style(style)
    size = int(st["size"])
    yc = H * caption_y(st, layout) / 100
    outline, shadow = st.get("outline", 7), st.get("shadow", 3)
    hk = hook or {}
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{st['font']},{size},{ass_color(st['color'])},&H000000FF,{ass_color(st['outline_color'])},&H78000000,0,0,0,0,100,100,0,0,1,{outline},{shadow},5,0,0,0,1
Style: Box,Arial,10,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Hook,{st['font']},{int(hk.get('size', 72))},{ass_color(hk.get('color', '#FFFFFF'))},&H000000FF,{ass_color(hk.get('bg', '#000000'))},{ass_color(hk.get('bg', '#000000'), 0)},0,0,0,0,100,100,0,0,3,20,0,8,80,80,170,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev: list[str] = []
    pw = prepare_words(words, st, keywords)
    groups = group_words(pw, int(st["words_per_line"]), int(st["max_chars"]))
    pad = size * 0.14
    line_in, line_out, wa = st.get("line_in", "none"), st.get("line_out", "none"), st.get("word_anim", "pop")
    progressive = st.get("reveal") == "progressive"
    box_mode = st.get("highlight_mode") == "box"
    soft = r"\blur0.8" if shadow else ""

    def emit(layer, s, e, x, y, tags, text, style="Cap"):
        s, e = s - offset, e - offset
        if e - s < 0.02 or (duration is not None and (e <= 0 or s >= duration)):
            return
        ev.append(f"Dialogue: {layer},{_t(s)},{_t(e)},{style},,0,0,0,,{{\\an5\\pos({x:.0f},{y:.0f}){tags}}}{text}")

    for li, line in enumerate(groups):
        ls = line[0]["s"]
        le = line[-1]["e"] + 0.25
        if li + 1 < len(groups):
            le = min(le, groups[li + 1][0]["s"])
        pos = layout_line(line, st, yc)
        # fond de ligne (boîte)
        if st.get("box"):
            alpha = int(255 * (1 - st.get("box_opacity", 70) / 100))
            for r in sorted({p["row"] for p in pos}):
                ps = [p for p in pos if p["row"] == r]
                x0 = min(p["x"] - p["w"] / 2 for p in ps) - pad * 1.6
                x1 = max(p["x"] + p["w"] / 2 for p in ps) + pad * 1.6
                hh = size * em_ratio(st["font"]) * 0.62
                y0, y1 = ps[0]["y"] - hh, ps[0]["y"] + hh
                fade = r"\fad(120,0)" if line_in != "none" else ""
                ev.append(f"Dialogue: 0,{_t(ls - offset)},{_t(le - offset)},Box,,0,0,0,,"
                          f"{{\\an7\\pos(0,0)\\1c{_c(st['box_color'])}\\1a&H{alpha:02X}&{fade}\\p1}}"
                          f"{_rrect(x0, y0, x1, y1, size * 0.25)}{{\\p0}}")
        for i, (w, p) in enumerate(zip(line, pos)):
            ws = w["s"]
            nxt = line[i + 1]["s"] if i + 1 < len(line) else le
            base_col = st["emphasis_color"] if w.get("x") else st["color"]
            pend_col = st["emphasis_color"] if w.get("x") else st.get("pending_color", st["color"])
            txt = _esc(p["text"])
            x, y = p["x"], p["y"]
            glow = (f"\\3c{_c(st['glow_color'])}\\bord{max(outline, 4) + 6}\\blur9\\1a&HFF&\\shad0"
                    if st.get("glow") else "")
            # 1) avant d'être prononcé
            if not progressive and ws > ls:
                intro = ""
                if line_in == "fade":
                    intro = r"\fad(140,0)"
                elif line_in == "slide_up":
                    intro = ""
                    tag_mv = f"\\move({x:.0f},{y + 50:.0f},{x:.0f},{y:.0f},0,200)\\fad(120,0)"
                elif line_in == "slide_left":
                    tag_mv = f"\\move({x + 90:.0f},{y:.0f},{x:.0f},{y:.0f},0,220)\\fad(100,0)"
                elif line_in == "zoom":
                    intro = r"\fscx70\fscy70\t(0,160,\fscx100\fscy100)\fad(80,0)"
                if line_in in ("slide_up", "slide_left"):
                    ev.append(f"Dialogue: 1,{_t(ls - offset)},{_t(ws - offset)},Cap,,0,0,0,,{{\\an5{tag_mv}\\c{_c(pend_col)}{soft}}}{txt}")
                    if glow:
                        ev.append(f"Dialogue: 0,{_t(ls - offset)},{_t(ws - offset)},Cap,,0,0,0,,{{\\an5{tag_mv}{glow}}}{txt}")
                else:
                    emit(1, ls, ws, x, y, f"\\c{_c(pend_col)}{soft}{intro}", txt)
                    if glow:
                        emit(0, ls, ws, x, y, glow + intro, txt)
            # 2) mot en cours
            if wa == "pop":
                anim = r"\fscx100\fscy100\t(0,80,\fscx116\fscy116)\t(80,170,\fscx108\fscy108)"
            elif wa == "zoom":
                anim = r"\fscx45\fscy45\t(0,110,\fscx115\fscy115)\t(110,190,\fscx104\fscy104)"
            elif wa == "bounce":
                anim = r"\fscx100\fscy100\t(0,90,\fscx112\fscy112)\t(90,180,\fscx104\fscy104)"
            else:
                anim = ""
            first_in = ""
            if ws <= ls + 0.01 and not progressive:
                first_in = {"fade": r"\fad(140,0)", "zoom": ""}.get(line_in, "")
            if wa == "bounce":
                mv = f"\\move({x:.0f},{y + 28:.0f},{x:.0f},{y:.0f},0,120)"
                act_col = st["highlight_text"] if box_mode else st["highlight"]
                ev_txt = f"{{\\an5{mv}\\c{_c(act_col)}{soft}{anim}{first_in}}}{txt}"
                s_, e_ = ws - offset, nxt - offset
                if e_ - s_ >= 0.02 and not (duration is not None and (e_ <= 0 or s_ >= duration)):
                    ev.append(f"Dialogue: 2,{_t(s_)},{_t(e_)},Cap,,0,0,0,,{ev_txt}")
            else:
                act_col = st["highlight_text"] if box_mode else st["highlight"]
                emit(2, ws, nxt, x, y, f"\\c{_c(act_col)}{soft}{anim}{first_in}", txt)
            if glow:
                emit(0, ws, nxt, x, y, glow + anim, txt)
            if box_mode:  # boîte colorée derrière le mot actif
                bw, bh = p["w"] / 2 + pad * 1.2, size * em_ratio(st["font"]) * 0.62
                rect = _rrect(x - bw, y - bh, x + bw, y + bh, size * 0.2)
                s_, e_ = ws - offset, nxt - offset
                if e_ - s_ >= 0.02:
                    sc = ""  # (libass ne sait pas animer l'échelle d'un dessin autour de son centre)
                    ev.append(f"Dialogue: 1,{_t(s_)},{_t(e_)},Box,,0,0,0,,{{\\an7\\pos(0,0)\\org({x:.0f},{y:.0f})\\1c{_c(st['highlight'])}"
                              f"{sc}\\p1}}{rect}{{\\p0}}")
            # 3) déjà prononcé
            out_t = r"\fad(0,120)" if line_out == "fade" else ""
            emit(1, nxt, le, x, y, f"\\c{_c(base_col)}{soft}{out_t}", txt)
            if glow:
                emit(0, nxt, le, x, y, glow + out_t, txt)
    if hook_text and hk.get("enabled", True):
        ev.append(f"Dialogue: 3,{_t(0)},{_t(float(hk.get('seconds', 3.5)))},Hook,,0,0,0,,"
                  f"{{\\fad(150,250)}}{_esc(hook_text)}")
    return head + "\n".join(ev) + "\n"


def sfx_times(words: list[dict], style: dict, keywords: list[str] | None = None) -> list[float]:
    """Instants où jouer le bruitage (début de ligne, mots forts ou chaque mot)."""
    st = full_style(style)
    if st.get("sfx", "none") == "none":
        return []
    pw = prepare_words(words, {**st, "emphasis": True}, keywords)
    on = st.get("sfx_on", "line")
    if on == "word":
        ts = [w["s"] for w in pw]
    elif on == "emphasis":
        ts = [w["s"] for w in pw if w.get("x")]
    else:
        ts = [g[0]["s"] for g in group_words(pw, int(st["words_per_line"]), int(st["max_chars"]))]
    out, last = [], -9.0
    for t in sorted(ts):  # au moins 0,35 s entre deux bruitages
        if t - last >= 0.35:
            out.append(t)
            last = t
    return out
