"""Sous-titres style TikTok/CapCut : génération ASS (libass) avec mot actif surligné.

`words` = [{"w": "salut", "s": 1.20, "e": 1.48}, ...] en secondes, relatifs à la source.
Le même découpage en lignes est utilisé par l'aperçu web (web/app.js → groupWords)
pour que l'aperçu et le rendu final soient identiques.
"""
from __future__ import annotations

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
    "karaoke": {"highlight": "#FFE500", "pop": True, "words_per_line": 3, "font": "Montserrat ExtraBold"},
    "hormozi": {"highlight": "#2BFF55", "pop": True, "words_per_line": 2, "font": "Montserrat Black"},
    "mrbeast": {"highlight": "#FF3B3B", "pop": True, "words_per_line": 2, "font": "Bangers"},
    "minimal": {"highlight": "#FFFFFF", "pop": False, "words_per_line": 5, "font": "Poppins ExtraBold",
                "uppercase": False, "size": 60},
    "gaming": {"highlight": "#00E5FF", "pop": True, "words_per_line": 3, "font": "Anton"},
}

W, H = 1080, 1920


def ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _t(sec: float) -> str:
    sec = max(sec, 0)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02}:{s:05.2f}"


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def group_words(words: list[dict], per_line: int, max_chars: int) -> list[list[dict]]:
    """Lignes de `per_line` mots max, coupées aussi sur la ponctuation, les pauses et la longueur."""
    lines, cur = [], []
    for i, w in enumerate(words):
        if not w.get("w", "").strip():
            continue
        if cur:
            gap = w["s"] - cur[-1]["e"]
            chars = sum(len(x["w"].strip()) + 1 for x in cur) + len(w["w"].strip())
            if (len(cur) >= per_line or gap > 0.6 or chars > max_chars
                    or cur[-1]["w"].strip()[-1:] in ".?!,"):
                lines.append(cur)
                cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def build_ass(words: list[dict], style: dict, offset: float = 0.0, duration: float | None = None,
              hook: dict | None = None, hook_text: str = "") -> str:
    st = {**style}
    font, bold = FONTS.get(st.get("font"), (st.get("font", "DejaVu Sans"), 1))
    size = int(st.get("size", 78))
    y = int(H * st.get("position", 70) / 100)
    outline, shadow = st.get("outline", 6), st.get("shadow", 2)
    col, hi, oc = ass_color(st["color"]), ass_color(st["highlight"]), ass_color(st["outline_color"])
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{col},{hi},{oc},&H80000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},5,60,60,0,1
Style: Hook,{font},{int((hook or {}).get('size', 72))},{ass_color((hook or {}).get('color', '#FFFFFF'))},&H000000FF,{ass_color((hook or {}).get('bg', '#000000'))},{ass_color((hook or {}).get('bg', '#000000'), 0)},{bold},0,0,0,100,100,0,0,3,18,0,8,80,80,170,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    up = st.get("uppercase", True)
    pop = st.get("pop", True)
    groups = group_words(words, int(st.get("words_per_line", 3)), int(st.get("max_chars", 18)))
    for li, line in enumerate(groups):
        # fin de ligne : jamais après le début de la suivante (sinon 2 lignes se superposent)
        line_end = line[-1]["e"] + 0.15
        if li + 1 < len(groups):
            line_end = min(line_end, groups[li + 1][0]["s"])
        texts = [(_esc(w["w"].strip().upper() if up else w["w"].strip())) for w in line]
        for i, w in enumerate(line):
            s = w["s"] - offset
            e = (line[i + 1]["s"] if i + 1 < len(line) else line_end) - offset
            if e - (w["s"] - offset) < 0.02:
                continue
            if duration is not None and (e <= 0 or s >= duration):
                continue
            parts = []
            for j, t in enumerate(texts):
                if j == i:
                    anim = r"\t(0,90,\fscx112\fscy112)\t(90,180,\fscx100\fscy100)" if pop else ""
                    parts.append(f"{{\\c{hi}{anim}}}{t}{{\\c{col}\\fscx100\\fscy100}}")
                else:
                    parts.append(t)
            ev.append(f"Dialogue: 0,{_t(s)},{_t(e)},Cap,,0,0,0,,{{\\pos({W // 2},{y})}}" + " ".join(parts))
    if hook_text and hook and hook.get("enabled", True):
        ev.append(f"Dialogue: 1,{_t(0)},{_t(float(hook.get('seconds', 3.5)))},Hook,,0,0,0,,"
                  f"{{\\fad(150,250)}}{_esc(hook_text)}")
    return head + "\n".join(ev) + "\n"
