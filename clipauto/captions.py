"""Sous-titres style TikTok/CapCut : génération ASS (libass).

Mot actif surligné (+ « pop »), mots importants mis en valeur (2e couleur), ponctuation
nettoyée, « euh / bah » retirés, fond en boîte optionnel, position automatique sur la
jonction cam/jeu en format 50/50.

`words` = [{"w": "salut", "s": 1.20, "e": 1.48}, ...] en secondes.
L'aperçu web (web/app.js → prepareWords / groupWords) applique EXACTEMENT les mêmes règles.
"""
from __future__ import annotations

import re

from .virality import EMOTION, FILLERS

FONTS = {  # nom affiché → (famille ASS, gras)
    "Montserrat ExtraBold": ("Montserrat ExtraBold", 0),
    "Montserrat Black": ("Montserrat Black", 0),
    "Poppins Black": ("Poppins Black", 0),
    "Poppins ExtraBold": ("Poppins ExtraBold", 0),
    "Anton": ("Anton", 0),
    "Bangers": ("Bangers", 0),
    "Bebas Neue": ("Bebas Neue", 0),
    "DejaVu Sans": ("DejaVu Sans", 1),
}

PRESETS = {
    "karaoke": {"font": "Montserrat Black", "highlight": "#FFE500", "emphasis_color": "#FF4D4D", "pop": True,
                "words_per_line": 3, "uppercase": True, "size": 84, "box": False, "outline": 7, "shadow": 3},
    "hormozi": {"font": "Montserrat Black", "highlight": "#2BFF55", "emphasis_color": "#FFE500", "pop": True,
                "words_per_line": 2, "uppercase": True, "size": 92, "box": False, "outline": 8, "shadow": 4},
    "mrbeast": {"font": "Bangers", "highlight": "#FFE500", "emphasis_color": "#FF3B3B", "pop": True,
                "words_per_line": 2, "uppercase": True, "size": 100, "box": False, "outline": 9, "shadow": 5},
    "boite": {"font": "Poppins Black", "highlight": "#FFE500", "emphasis_color": "#FFE500", "pop": False,
              "words_per_line": 4, "uppercase": False, "size": 66, "box": True, "box_color": "#000000",
              "box_opacity": 70, "outline": 0, "shadow": 0},
    "minimal": {"font": "Poppins ExtraBold", "highlight": "#FFFFFF", "emphasis_color": "#FFFFFF", "pop": False,
                "words_per_line": 5, "uppercase": False, "size": 60, "box": False, "outline": 4, "shadow": 2},
    "gaming": {"font": "Anton", "highlight": "#00E5FF", "emphasis_color": "#FF2BD6", "pop": True,
               "words_per_line": 3, "uppercase": True, "size": 96, "box": False, "outline": 8, "shadow": 3},
}

W, H = 1080, 1920
_PUNCT = re.compile(r"[.,;:…«»\"“”()]+")


def ass_color(hex_color: str, alpha: int = 0) -> str:
    h = (hex_color or "#FFFFFF").lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _t(sec: float) -> str:
    sec = max(sec, 0)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02}:{s:05.2f}"


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


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
                    "x": style.get("emphasis", True) and is_emphasis(raw, kws)})
    return out


def group_words(words: list[dict], per_line: int, max_chars: int) -> list[list[dict]]:
    """Lignes de `per_line` mots max, coupées aussi sur la ponctuation, les pauses et la longueur."""
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
    """Position verticale en % : sur la jonction cam/jeu en format split si « auto »."""
    if style.get("auto_position", True) and layout and layout.get("mode") == "split":
        return float(layout.get("split_ratio", 0.42)) * 100
    return float(style.get("position", 70))


def build_ass(words: list[dict], style: dict, offset: float = 0.0, duration: float | None = None,
              hook: dict | None = None, hook_text: str = "", layout: dict | None = None,
              keywords: list[str] | None = None) -> str:
    st = {**style}
    font, bold = FONTS.get(st.get("font"), (st.get("font", "DejaVu Sans"), 1))
    size = int(st.get("size", 84))
    y = int(H * caption_y(st, layout) / 100)
    outline, shadow = st.get("outline", 7), st.get("shadow", 3)
    col, hi, oc = ass_color(st["color"]), ass_color(st["highlight"]), ass_color(st["outline_color"])
    em = ass_color(st.get("emphasis_color", st["highlight"]))
    if st.get("box"):
        alpha = int(255 * (1 - st.get("box_opacity", 70) / 100))
        border = f"3,{max(int(size * 0.22), 8)},0"
        back = oc_box = ass_color(st.get("box_color", "#000000"), alpha)
        oc = oc_box
    else:
        border, back = f"1,{outline},{shadow}", "&H96000000"
    hk = hook or {}
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{col},{hi},{oc},{back},{bold},0,0,0,100,100,1,0,{border},5,60,60,0,1
Style: Hook,{font},{int(hk.get('size', 72))},{ass_color(hk.get('color', '#FFFFFF'))},&H000000FF,{ass_color(hk.get('bg', '#000000'))},{ass_color(hk.get('bg', '#000000'), 0)},{bold},0,0,0,100,100,0,0,3,20,0,8,80,80,170,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    up = st.get("uppercase", True)
    pop = st.get("pop", True)
    soft = r"\blur1.2" if not st.get("box") and shadow else ""
    pw = prepare_words(words, st, keywords)
    groups = group_words(pw, int(st.get("words_per_line", 3)), int(st.get("max_chars", 18)))
    for li, line in enumerate(groups):
        line_end = line[-1]["e"] + 0.15
        if li + 1 < len(groups):  # jamais après le début de la ligne suivante (pas de superposition)
            line_end = min(line_end, groups[li + 1][0]["s"])
        texts = [_esc(w["w"].upper() if up else w["w"]) for w in line]
        for i, w in enumerate(line):
            s = w["s"] - offset
            e = (line[i + 1]["s"] if i + 1 < len(line) else line_end) - offset
            if e - s < 0.02 or (duration is not None and (e <= 0 or s >= duration)):
                continue
            parts = []
            for j, (t, ww) in enumerate(zip(texts, line)):
                base = em if ww.get("x") else col
                if j == i:
                    anim = r"\fscx100\fscy100\t(0,80,\fscx114\fscy114)\t(80,170,\fscx106\fscy106)" if pop else ""
                    parts.append(f"{{\\c{hi}{anim}}}{t}{{\\c{col}\\fscx100\\fscy100}}")
                elif ww.get("x"):
                    parts.append(f"{{\\c{base}}}{t}{{\\c{col}}}")
                else:
                    parts.append(t)
            intro = r"\fad(60,0)" if i == 0 else ""
            ev.append(f"Dialogue: 0,{_t(s)},{_t(e)},Cap,,0,0,0,,{{\\an5\\pos({W // 2},{y}){soft}{intro}}}"
                      + " ".join(parts))
    if hook_text and hk.get("enabled", True):
        ev.append(f"Dialogue: 1,{_t(0)},{_t(float(hk.get('seconds', 3.5)))},Hook,,0,0,0,,"
                  f"{{\\fad(150,250)}}{_esc(hook_text)}")
    return head + "\n".join(ev) + "\n"
