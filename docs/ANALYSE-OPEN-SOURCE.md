# Analyse des briques open source — SaaS de clipping de streams

Analyse faite le 2026-11-18 sur les dépôts clonés (dernier commit indiqué).

## Verdict par dépôt

| Dépôt | Licence | Dernier commit | Usage SaaS | Ce qu'on prend |
|---|---|---|---|---|
| fralapo/clippyme | **MIT** | 2026-10-13 | ✅ Base principale | Live monitor Kick/Twitch/YouTube (segments, backoff, rattrapage), Gemini pour choisir et classer les moments, recadrage 9:16 selon la personne qui parle, sous-titres animés, suppression des silences, publication planifiée (Zernio), jobs qui reprennent après crash |
| mutonby/openshorts | **MIT** | 2026-11-18 | ✅ À piocher | Layouts SPLIT/SCREENCAST, rendu Remotion, hooks et titres par plateforme, publication via Upload-Post, API/MCP |
| ColinGPT9/clips-studio (Clips Kitty) | **AGPL-3.0** | 2026-11-18 | ⚠️ Idées seulement, pas de code | Score sur 5 signaux normalisés par vidéo, bonus du chat Twitch (nombre de spectateurs distincts qui écrivent), « silence → explosion », comparaison des finalistes deux à deux, profils de créateurs (blagues récurrentes) |
| FujiwaraChoki/supoclip | **Non commerciale** | 2026-11-18 | ❌ Exclu | — |
| jekku0966/HighlightMiner | MIT | 2026-09-03 | ✅ Petit, lisible | Fusion audio + vitesse du chat + transcription, pré-roll et post-roll |
| artkulak/twitch-stream-highlights-detection | Domaine public | 2021 | Référence | Score temps réel par fenêtres de 10 s |
| streamlink/streamlink | BSD-2 | 2026-11-14 | ✅ | Plugins `kick.py`, `twitch.py`, `youtube.py` confirmés |

## Ce qui manque partout (= notre différenciation)
1. **Le chat en direct comme déclencheur** : aujourd'hui, tous les outils analysent après coup (segment ou VOD). Pourtant, Kick supprime le chat à la fin du stream, donc il faut le capter en direct.
2. **Validation humaine en 1 clic** (Discord + application web) avant publication.
3. **Multi-utilisateurs** : agences et réseaux de clippers, plusieurs comptes sociaux, quotas, facturation.
4. **Boucle virale** : récupérer les vues des clips publiés pour réajuster les poids de détection par streamer.

## Pipeline cible
monitor (API + Streamlink) → enregistrement en segments + chat websocket/IRC
→ signaux par seconde (audio : volume et rafales de bruit, YAMNet rires/cris ; chat : spectateurs distincts/s, emotes ; vidéo : coupes, mouvement)
→ pics détectés → fenêtre [-40 s, +20 s] → Whisper → le LLM juge et compare les finalistes deux à deux, puis écrit le hook et le titre
→ rendu 9:16 (logique ClippyMe/OpenShorts) → Discord/app : Approuver/Rejeter
→ publication (Post for Me / Upload-Post / Zernio, interchangeables) → stats → recalibrage
