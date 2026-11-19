"""Étape 5 : notification + validation humaine sur Discord (boutons Approuver / Rejeter).

Sans DISCORD_BOT_TOKEN, repli console : les clips restent « pending » et
s'approuvent avec `python -m clipauto approve <id>`.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger(__name__)
OnDecision = Callable[[int, bool], Awaitable[None]]


class ConsoleReview:
    async def start(self) -> None: ...

    async def notify(self, text: str) -> None:
        log.info("[notif] %s", text)

    async def send_clip(self, clip_id: int, path: Path, text: str) -> None:
        log.info("[clip #%s en attente] %s — %s", clip_id, path, text)


class DiscordReview:
    def __init__(self, token: str, channel_id: int, on_decision: OnDecision):
        import discord
        self.discord, self.token, self.channel_id = discord, token, channel_id
        self.on_decision = on_decision
        self.client = discord.Client(intents=discord.Intents.default())

    async def start(self) -> None:
        import asyncio
        await self.client.login(self.token)  # erreur claire si le token est invalide
        self._conn = asyncio.create_task(self.client.connect())
        ready = asyncio.create_task(self.client.wait_until_ready())
        done, _ = await asyncio.wait({ready, self._conn}, return_when=asyncio.FIRST_COMPLETED)
        if self._conn in done:
            ready.cancel()
            self._conn.result()  # relance l'erreur de connexion
            raise RuntimeError("connexion Discord fermée avant d'être prête")
        log.info("bot Discord connecté")

    async def _channel(self):
        return self.client.get_channel(self.channel_id) or await self.client.fetch_channel(self.channel_id)

    async def notify(self, text: str) -> None:
        await (await self._channel()).send(text)

    async def send_clip(self, clip_id: int, path: Path, text: str) -> None:
        d, review = self.discord, self

        class View(d.ui.View):
            def __init__(self):
                super().__init__(timeout=None)

            @d.ui.button(label="Approuver", style=d.ButtonStyle.success, emoji="✅")
            async def ok(self, inter, _btn):
                await inter.response.edit_message(content=f"{text}\n✅ approuvé par {inter.user}", view=None)
                await review.on_decision(clip_id, True)

            @d.ui.button(label="Rejeter", style=d.ButtonStyle.danger, emoji="🗑️")
            async def ko(self, inter, _btn):
                await inter.response.edit_message(content=f"{text}\n🗑️ rejeté par {inter.user}", view=None)
                await review.on_decision(clip_id, False)

        ch = await self._channel()
        if path.stat().st_size > 24 * 1024 * 1024:  # limite d'upload Discord
            await ch.send(f"{text}\n(fichier trop lourd pour Discord : {path})", view=View())
        else:
            await ch.send(text, file=d.File(str(path)), view=View())


def make_review(on_decision: OnDecision):
    tok, ch = os.environ.get("DISCORD_BOT_TOKEN"), os.environ.get("DISCORD_CHANNEL_ID")
    if tok and ch:
        return DiscordReview(tok, int(ch), on_decision)
    log.warning("Discord non configuré → validation en console")
    return ConsoleReview()
