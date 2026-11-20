from clipauto.virality import analyze_text, combine, explain_signals


def _w(text, start=0.0, step=0.35):
    return [{"w": w, "s": start + i * step, "e": start + i * step + 0.3} for i, w in enumerate(text.split())]


def test_emotional_clip_scores_higher_than_flat_one():
    hot = _w("Attends attends ! Oh putain frère il a volé la voiture de police ! Non non non c'est pas possible !")
    flat = _w("donc là on va aller à la banque et ensuite on verra pour la suite du programme de ce soir.")
    a, b = analyze_text(hot, 0, 40, []), analyze_text(flat, 0, 40, [])
    assert a["score"] > b["score"]
    assert any("Accroche" in r for r in a["reasons"])


def test_silence_is_flagged():
    r = analyze_text([], 0, 30)
    assert r["flags"]


def test_explain_signals_ratio():
    d = {"z": {"chat_rate": 4.0}, "raw": {"chat_rate": 4.8}, "base": {"chat_rate": 1.1}}
    s = explain_signals(d)[0]
    assert s["strong"] and s["ratio"] == 4.4


def test_combine_without_llm():
    assert combine(80, 40, None) == round((80 * 0.5 + 40 * 0.35) / 0.85)


def test_guess_lang_and_skip_in_captions():
    from clipauto.captions import prepare_words
    from clipauto.clipper import guess_lang
    assert guess_lang("I don't do this shit for free")[0] == "en"
    assert guess_lang("Eh bah putain les gars")[0] == "fr"
    w = [{"w": "salut", "s": 0, "e": .3}, {"w": "money", "s": .4, "e": .7, "skip": True}]
    assert [x["w"] for x in prepare_words(w, {})] == ["salut"]
