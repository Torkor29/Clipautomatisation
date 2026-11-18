# Clipautomatisation

Clipping automatique de lives Twitch / Kick / YouTube, d'après le workflow
« GTA clipping system » : surveillance des lives → enregistrement Streamlink →
détection des moments forts (chat + rires + audio) → clip 9:16 sous-titré →
validation Discord → publication multi-réseaux via Post for Me.

```
monitor.py   API Helix Twitch, kick.com/api/v2, Streamlink (YouTube / repli)   toutes les 2 min
recorder.py  streamlink | ffmpeg → segments de 10 s, fenêtre glissante 15 min
chat.py      chat EN DIRECT : IRC Twitch anonyme, WebSocket Kick
audio.py     volume dB par 0,5 s de chaque segment
detector.py  fusion de 5 signaux normalisés par stream (médiane/MAD) → déclenchement
clipper.py   [pic − 40 s, pic + 20 s] → 1080x1920 fond flou + sous-titres faster-whisper
review.py    bot Discord : notif « live », clip + boutons Approuver / Rejeter
publisher.py Post for Me : upload signé → post sur tous les comptes connectés
app.py       orchestration, store.py SQLite des clips
```

## Lancer

```bash
cp .env.example .env            # clés Twitch, Discord, Post for Me
cp config.example.yaml config.yaml   # streamers à suivre, seuils
pip install -r requirements.txt   # + ffmpeg installé
python -m clipauto live           # qui est en live maintenant ?
python -m clipauto run            # boucle complète
python -m clipauto pending | approve <id> | reject <id>   # sans Discord
```

Sur VPS : `docker compose up -d --build`.

## Réglages clés (`config.yaml > detect`)
- `threshold` : plus bas = plus de clips. 2.0 par défaut ; 1.2–1.5 pour les petits streams.
- `weights` : importance de chaque signal (rires du chat pèsent le plus).
- Au moins 2 signaux doivent monter ensemble (un spammeur seul ne déclenche rien).

## Briques open source utilisées / étudiées
Voir `docs/ANALYSE-OPEN-SOURCE.md` (Streamlink, faster-whisper, idées de Clips Kitty,
HighlightMiner, ClippyMe, OpenShorts).
