from clipauto.overlays import audio_mix, clean, text_events


def test_text_events_and_clean():
    items = clean([{"id": "a", "type": "text", "start": 1, "end": 3, "text": "SALUT", "bg": "#ff0000"},
                   {"id": "b", "type": "image", "start": 2, "end": 1, "src": "asset:x.png"},       # fin < début
                   {"id": "c", "type": "video", "start": 0, "end": 2, "src": "../../etc/passwd"},  # chemin refusé
                   {"id": "d", "type": "audio", "start": 0, "end": 2, "src": "sfx:pop"}])
    assert [i["id"] for i in items] == ["a", "d"]
    ev = text_events(items, 10)
    assert any("SALUT" in e for e in ev) and any("\\p1" in e for e in ev)  # texte + boîte de fond


def test_audio_mix_with_ducking():
    parts, out = audio_mix("a0", [("1:a", {"start": 0, "end": 5, "duck": True, "volume": 30})], 10)
    f = ";".join(parts)
    assert "sidechaincompress" in f and "amix=inputs=2" in f and out == "amixo"
