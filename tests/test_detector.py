from clipauto.detector import Detector, classify


def test_classify():
    assert classify("KEKW KEKW") == (1, 0)
    assert classify("ptdrrr") == (1, 0)
    assert classify("POG no way") == (0, 1)
    assert classify("salut") == (0, 0)


def test_detects_spike_only_when_several_signals_rise():
    d = Detector(window=10, warmup=0, cooldown=0)
    t = 1000.0
    for i in range(60):  # 10 min de chat calme
        for j in range(5):
            d.add_message(t + j, f"u{(i * 5 + j) % 20}", "salut")
        d.add_audio(t, -30)
        t += 10
        assert d.step(t) is None
    for j in range(80):  # explosion de rires de plein de gens + cri
        d.add_message(t + j / 10, f"v{j}", "KEKW 😂")
    d.add_audio(t + 5, -8)
    trig = d.step(t + 10)
    assert trig is not None and trig.score >= 2


def test_single_spammer_does_not_trigger():
    d = Detector(window=10, warmup=0, cooldown=0)
    t = 0.0
    for i in range(60):
        for j in range(5):
            d.add_message(t + j, f"u{j}", "hello")
        t += 10
        d.step(t)
    for j in range(40):
        d.add_message(t + j / 5, "bot", "hello")
    assert d.step(t + 10) is None


def test_single_laugh_on_silent_history_is_not_huge():
    d = Detector(window=10, warmup=0, cooldown=0)
    t = 0.0
    for i in range(30):
        d.add_message(t + 1, f"u{i % 3}", "salut")
        t += 10
        d.step(t)
    d.add_message(t + 1, "x", "KEKW")
    d.step(t + 10)
    assert abs(d.timeline[-1][2]["laugh_emotes"]) <= 10
