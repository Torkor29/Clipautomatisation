from clipauto.story import story_window


def _w(text, start, step=0.4):
    return [{"w": w, "s": start + i * step, "e": start + i * step + 0.3} for i, w in enumerate(text.split())]


def test_starts_at_sentence_after_pause_and_ends_after_reaction():
    words = (_w("bon on va au magasin acheter des trucs.", 2) +
             _w("Attends regarde la police arrive !", 30) +       # setup ~ 25 s avant le pic
             _w("non non il m'a eu frère c'est mort.", 52) +       # pic à 55
             _w("bref on repart.", 75))
    curve = [(t, 0.3) for t in range(0, 50)] + [(t, 4.0) for t in range(50, 62)] + [(t, 0.5) for t in range(62, 100)]
    r = story_window(words, [55], curve, 100, 20, 45)
    s0, e0 = r["segments"][0][0], r["segments"][-1][1]
    assert 29 <= s0 <= 30.1          # début = « Attends regarde… » (après une pause, accroche)
    assert 60 <= e0 <= 70            # fin après la réaction, avant « bref on repart »
    assert any("Début" in x for x in r["reasons"])


def test_two_peaks_merge_and_cut_the_gap():
    words = _w("Attends regarde ça !", 5) + _w("oh non !", 18) + _w("blabla " * 30, 25, 0.9) + _w("encore lui !", 70) + _w("incroyable.", 74)
    curve = [(t, 0.2) for t in range(0, 100)]
    for a, b in ((15, 24), (68, 78)):
        for i in range(a, b):
            curve[i] = (i, 4.0)
    r = story_window(words, [20, 72], curve, 100, 20, 45)
    total = sum(b - a for a, b in r["segments"])
    assert len(r["segments"]) >= 2 and total <= 46
