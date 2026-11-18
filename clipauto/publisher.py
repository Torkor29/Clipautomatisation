"""Étape 6 : publication multi-réseaux via Post for Me (SDK officiel `post-for-me`).

Flux : demander une URL d'upload signée → PUT du fichier → créer le post sur
les comptes sociaux connectés (TikTok, YouTube Shorts, Instagram, X…).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import aiohttp

log = logging.getLogger(__name__)


class PostForMe:
    def __init__(self, social_accounts: list[str], caption_template: str):
        from post_for_me import AsyncPostForMe
        if not os.environ.get("POST_FOR_ME_API_KEY"):
            raise RuntimeError("POST_FOR_ME_API_KEY manquant")
        self.client = AsyncPostForMe()
        self.accounts, self.template = social_accounts, caption_template

    async def list_accounts(self):
        return await self.client.social_accounts.list()

    async def publish(self, video: Path, streamer: str, platform: str, caption: str | None = None) -> str:
        up = await self.client.media.create_upload_url()
        async with aiohttp.ClientSession() as s:
            async with s.put(up.upload_url, data=video.read_bytes(),
                             headers={"Content-Type": "video/mp4"}) as r:
                r.raise_for_status()
        text = caption or self.template.format(streamer=streamer, platform=platform)
        post = await self.client.social_posts.create(
            caption=text, social_accounts=self.accounts, media=[{"url": up.media_url}])
        log.info("publié %s → post %s", video.name, post.id)
        return post.id
