"""Lecture du chat en direct : chaque message → (horodatage, auteur, texte).

Twitch : IRC WebSocket anonyme officiel (justinfanXXXX, lecture seule).
Kick   : WebSocket Pusher utilisé par kick.com (non officiel, configurable).
Le chat est capté EN DIRECT : Kick ne conserve pas le chat après le stream.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from typing import Awaitable, Callable

import websockets

log = logging.getLogger(__name__)
OnMsg = Callable[[float, str, str], Awaitable[None] | None]


async def _emit(cb: OnMsg, *a) -> None:
    r = cb(*a)
    if asyncio.iscoroutine(r):
        await r


async def twitch_chat(channel: str, on_msg: OnMsg, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with websockets.connect("wss://irc-ws.chat.twitch.tv:443") as ws:
                await ws.send("CAP REQ :twitch.tv/tags")
                await ws.send("PASS SCHMOOPIIE")
                await ws.send(f"NICK justinfan{random.randint(10000, 99999)}")
                await ws.send(f"JOIN #{channel.lower()}")
                async for raw in ws:
                    if stop.is_set():
                        return
                    for line in str(raw).split("\r\n"):
                        if line.startswith("PING"):
                            await ws.send("PONG :tmi.twitch.tv")
                        elif " PRIVMSG " in line:
                            _, _, rest = line.partition(" :") if line.startswith("@") else ("", "", line[1:])
                            user = rest.split("!", 1)[0]
                            text = rest.split(" :", 1)[1] if " :" in rest else ""
                            await _emit(on_msg, time.time(), user, text)
        except Exception as e:  # coupure réseau → reconnexion
            log.warning("chat twitch %s: %s, reconnexion", channel, e)
            await asyncio.sleep(5)


KICK_PUSHER = os.environ.get(
    "KICK_PUSHER_URL",
    "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679?protocol=7&client=js&version=8.4.0&flash=false")


async def kick_chat(chatroom_id: int, on_msg: OnMsg, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with websockets.connect(KICK_PUSHER) as ws:
                await ws.send(json.dumps({"event": "pusher:subscribe",
                                          "data": {"channel": f"chatrooms.{chatroom_id}.v2"}}))
                async for raw in ws:
                    if stop.is_set():
                        return
                    m = json.loads(raw)
                    if m.get("event") == "pusher:ping":
                        await ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
                    elif "ChatMessage" in m.get("event", ""):
                        d = json.loads(m["data"])
                        await _emit(on_msg, time.time(), d["sender"]["username"], d.get("content", ""))
        except Exception as e:
            log.warning("chat kick %s: %s, reconnexion", chatroom_id, e)
            await asyncio.sleep(5)
