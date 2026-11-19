"""Étape 1 : détecter quand un streamer passe en live (Twitch, Kick, YouTube)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import aiohttp

from .config import Streamer

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) clipauto/0.1"}


class TwitchAPI:
    """API Helix officielle, jeton « app » (client credentials)."""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id, self.client_secret = client_id, client_secret
        self._token: str | None = None
        self._exp = 0.0

    async def _auth(self, s: aiohttp.ClientSession) -> str:
        if self._token and time.time() < self._exp - 60:
            return self._token
        async with s.post("https://id.twitch.tv/oauth2/token", data={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "grant_type": "client_credentials"}) as r:
            r.raise_for_status()
            d = await r.json()
        self._token, self._exp = d["access_token"], time.time() + d["expires_in"]
        return self._token

    async def live(self, s: aiohttp.ClientSession, logins: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for i in range(0, len(logins), 100):
            tok = await self._auth(s)
            params = [("user_login", l) for l in logins[i:i + 100]]
            async with s.get("https://api.twitch.tv/helix/streams", params=params, headers={
                    "Client-Id": self.client_id, "Authorization": f"Bearer {tok}"}) as r:
                r.raise_for_status()
                for st in (await r.json())["data"]:
                    out[st["user_login"].lower()] = {"title": st["title"], "game": st["game_name"],
                                                     "viewers": st["viewer_count"]}
        return out


async def kick_live(s: aiohttp.ClientSession, slug: str) -> dict | None:
    """Endpoint public non officiel kick.com/api/v2 (peut casser, Cloudflare)."""
    try:
        async with s.get(f"https://kick.com/api/v2/channels/{slug}", headers=UA) as r:
            if r.status != 200:
                return await _streamlink_live(f"https://kick.com/{slug}")
            d = await r.json(content_type=None)
    except aiohttp.ClientError:
        return await _streamlink_live(f"https://kick.com/{slug}")
    ls = d.get("livestream")
    if not ls:
        return None
    return {"title": ls.get("session_title"), "viewers": ls.get("viewer_count"),
            "chatroom_id": (d.get("chatroom") or {}).get("id")}


async def _streamlink_live(url: str) -> dict | None:
    """Repli universel : Streamlink sait dire si un flux est disponible (YouTube, Kick…)."""
    proc = await asyncio.create_subprocess_exec(
        "streamlink", "--json", url, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    try:
        d = json.loads(out or b"{}")
    except json.JSONDecodeError:
        return None
    if d.get("streams"):
        return {"title": (d.get("metadata") or {}).get("title")}
    return None


class LiveMonitor:
    """Interroge chaque plateforme toutes les `poll_seconds` et émet on_live / on_offline."""

    def __init__(self, streamers, poll_seconds, on_live, on_offline):
        # streamers : liste OU fonction qui renvoie la liste (rechargée à chaque tour)
        self._streamers, self.poll = streamers, poll_seconds
        self.on_live, self.on_offline = on_live, on_offline
        self.state: dict[str, bool] = {}
        cid, sec = os.environ.get("TWITCH_CLIENT_ID"), os.environ.get("TWITCH_CLIENT_SECRET")
        self.twitch = TwitchAPI(cid, sec) if cid and sec else None

    @property
    def streamers(self) -> list[Streamer]:
        return self._streamers() if callable(self._streamers) else self._streamers

    async def check_once(self, s: aiohttp.ClientSession) -> dict[str, dict | None]:
        res: dict[str, dict | None] = {}
        streamers = self.streamers
        tw = [x for x in streamers if x.platform == "twitch"]
        if tw:
            if self.twitch:
                live = await self.twitch.live(s, [x.channel.lower() for x in tw])
                for x in tw:
                    res[x.key] = live.get(x.channel.lower())
            else:
                for x in tw:
                    res[x.key] = await _streamlink_live(x.url)
        for x in streamers:
            if x.platform == "kick":
                res[x.key] = await kick_live(s, x.channel)
            elif x.platform == "youtube":
                res[x.key] = await _streamlink_live(x.url)
        return res

    async def run(self) -> None:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            while True:
                try:
                    res = await self.check_once(s)
                except Exception:  # réseau, quota… on retente au prochain tour
                    log.exception("échec du polling")
                    res = {}
                keys = {x.key for x in self.streamers}
                for k in [k for k in self.state if k not in keys and self.state[k]]:
                    self.state[k] = False  # streamer retiré/désactivé pendant son live
                    await self.on_offline(k)
                for x in self.streamers:
                    if x.key not in res:
                        continue
                    info, was = res[x.key], self.state.get(x.key, False)
                    if info and not was:
                        await self.on_live(x, info)
                    elif not info and was:
                        await self.on_offline(x.key)
                    self.state[x.key] = bool(info)
                poll = self.poll() if callable(self.poll) else self.poll
                await asyncio.sleep(poll)
