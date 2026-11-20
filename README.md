# ClipAuto

Web app de clipping automatique de lives **Twitch / Kick / YouTube** (style Opus Clip) :
surveillance des lives → enregistrement Streamlink → détection des moments forts
(chat, rires, hype, mots-clés, volume) → clip 9:16 avec sous-titres karaoké
synchronisés au mot → éditeur intégré → validation (web ou Discord) → publication
multi-réseaux via Post for Me.

## Interface (http://IP:8000)
- **Clips** : bibliothèque avec score viral, aperçu au survol, approuver / rejeter / télécharger.
- **Éditeur** (façon CapCut) :
  - **Découpe** : forme d'onde audio, poignées début/fin, « caler sur les phrases »
  - **Sous-titres** : correction mot par mot, re-transcription, décalage de synchro
  - **Style** : 5 presets (karaoke, hormozi, mrbeast, minimal, gaming), 8 polices, couleurs, taille, position, mots par ligne, animation pop, titre d'accroche
  - **Cadrage** : fond flou + zoom, plein écran (bande à placer), facecam + jeu (2 cadres à placer), bandes noires
  - vitesse 0.9×–1.25×, aperçu identique au rendu final, rendu MP4 1080×1920
- **Streamers** : ajout par nom ou lien, statut live, courbe de détection en temps réel, réglages propres à chaque streamer.
- **Importer** : lien de VOD (yt-dlp) ou fichier → N meilleurs moments.
- **Réglages** : sensibilité, poids de chaque signal, listes de mots (rires, hype, mots-clés perso), durées min/max, avant/après le pic, langue, précision de la transcription, style par défaut, publication auto.

## Lancer
```bash
cp .env.example .env     # TWITCH_*, DISCORD_* (optionnel), POST_FOR_ME_API_KEY, APP_PASSWORD
docker compose up -d --build
# ou sans Docker : pip install -r requirements.txt && python -m clipauto web
```

## Architecture
```
clipauto/web.py       API FastAPI + fichiers statiques web/
clipauto/engine.py    sessions live, création de clips, imports, rendus, publication
clipauto/monitor.py   détection des lives (API Helix, kick.com, Streamlink)
clipauto/recorder.py  Streamlink → segments de 10 s (fenêtre glissante)
clipauto/chat.py      chat en direct (IRC Twitch, WebSocket Kick)
clipauto/detector.py  fusion des signaux normalisés par stream
clipauto/clipper.py   extraction, transcription faster-whisper (mots), découpe intelligente, rendu ffmpeg
clipauto/captions.py  sous-titres ASS karaoké (même logique que l'aperçu web)
clipauto/db.py        SQLite : réglages, streamers, clips, jobs
web/                  interface (HTML/CSS/JS sans build)
fonts/                polices OFL (Montserrat, Poppins, Anton, Bangers, Bebas Neue)
```
Analyse des projets open source étudiés : `docs/ANALYSE-OPEN-SOURCE.md`.

## Front sur Vercel, moteur sur le VPS
1. VPS — dans `.env` : `APP_PASSWORD=…`, `DOMAIN=<ip-avec-tirets>.sslip.io` (ou ton domaine), `CORS_ORIGINS=https://<ton-projet>.vercel.app`
   puis `docker compose --profile https up -d --build` (Caddy obtient le certificat HTTPS tout seul ; ports 80/443 ouverts).
   Si les ports 80/443 sont déjà pris par un autre site (nginx), ajoute plutôt un bloc `proxy_pass http://127.0.0.1:8000;`
   pour ce domaine dans ta config nginx + `certbot --nginx`.
2. Vercel — importe le dépôt, variable d'environnement `CLIPAUTO_API=https://<DOMAIN>` ; le reste est dans `vercel.json`.
3. Ouvre l'adresse Vercel, entre le mot de passe : c'est tout.
