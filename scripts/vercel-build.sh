#!/bin/sh
# Build Vercel : le front statique (dossier web/) + les polices, et l'adresse du VPS.
set -e
mkdir -p web/fonts
cp fonts/*.ttf web/fonts/
if [ -z "$CLIPAUTO_API" ]; then echo "⚠️  Variable CLIPAUTO_API manquante (ex. https://1-2-3-4.sslip.io)"; exit 1; fi
printf 'window.CLIPAUTO_API = "%s";\n' "$CLIPAUTO_API" > web/config.js
echo "Front prêt pour $CLIPAUTO_API"
