from clipauto.titles import suggest


def _w(t):
    return [{"w": w, "s": i * .3, "e": i * .3 + .25} for i, w in enumerate(t.split())]


def test_quote_must_be_full_short_sentence():
    t = suggest(_w("Il y a un troisième actor dans la. Eh bah putain les gars !"), "squeezie", {"z": {"chat_rate": 4}})
    assert t[0].replace("\xa0", " ").startswith("« Eh bah putain les gars") and not any("dans la" in x for x in t)


def test_templates_follow_signals():
    t = suggest(_w("ok"), "jltomy", {"z": {"laugh_emotes": 6}})
    assert any("rire" in x or "😂" in x for x in t[:3])
