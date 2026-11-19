from clipauto.captions import build_ass, group_words
from clipauto.clipper import smart_trim

W = [{"w": w, "s": i * 0.4, "e": i * 0.4 + 0.3} for i, w in enumerate("salut les gars. on y va maintenant tous ensemble".split())]


def test_group_breaks_on_punctuation_and_size():
    lines = group_words(W, 3, 18)
    assert [x["w"] for x in lines[0]] == ["salut", "les", "gars."]
    assert all(len(l) <= 3 for l in lines)


def test_ass_lines_never_overlap():
    ass = build_ass(W, {"font": "Anton", "size": 80, "color": "#FFFFFF", "highlight": "#FFE500",
                        "outline_color": "#000000", "words_per_line": 3, "position": 70})
    ev = [l.split(",")[1:3] for l in ass.splitlines() if l.startswith("Dialogue")]
    to_s = lambda t: sum(float(x) * m for x, m in zip(t.split(":"), (3600, 60, 1)))
    spans = sorted((to_s(a), to_s(b)) for a, b in ev)
    assert all(spans[i][1] <= spans[i + 1][0] + 1e-6 for i in range(len(spans) - 1))


def test_smart_trim_respects_bounds():
    words = [{"w": "x.", "s": t, "e": t + 0.3} for t in range(0, 90, 2)]
    s, e = smart_trim(words, peak=60, total=90, min_s=30, max_s=45, pre=40, post=20)
    assert 30 <= e - s <= 45 and s <= 58 and e >= 60


def test_timeline_with_transitions_and_speed():
    from clipauto.clipper import output_duration, remap_words, timeline
    e = {"speed": 1.0, "segments": [{"s": 0, "e": 10}, {"s": 20, "e": 30, "transition": {"type": "fade", "duration": 0.5}},
                                    {"s": 40, "e": 46, "effect": "slowmo", "transition": {"type": "cut"}}]}
    tl = timeline(e)
    assert tl[1]["out_start"] == 9.5 and tl[2]["out_start"] == 19.5
    assert abs(output_duration(e) - (19.5 + 8)) < 1e-6
    w = remap_words([{"w": "a", "s": 21, "e": 21.5}, {"w": "b", "s": 15, "e": 15.3}], e)
    assert [x["w"] for x in w] == ["a"] and abs(w[0]["s"] - 10.5) < 1e-6
