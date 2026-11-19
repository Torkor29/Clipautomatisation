"""CLI : python -m clipauto web | live | add <platform> <chaine>"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(prog="clipauto")
    ap.add_argument("--data", default=os.environ.get("DATA_DIR", "data"))
    sub = ap.add_subparsers(dest="cmd")
    w = sub.add_parser("web", help="interface web + moteur (par défaut)")
    w.add_argument("--host", default="0.0.0.0")
    w.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    sub.add_parser("live", help="qui est en live parmi les streamers suivis")
    a2 = sub.add_parser("add", help="ajouter un streamer")
    a2.add_argument("platform", choices=["twitch", "kick", "youtube"])
    a2.add_argument("channel")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from .config import load_dotenv
    load_dotenv()

    if a.cmd in (None, "web"):
        import uvicorn
        from .web import create_app
        uvicorn.run(create_app(Path(a.data)), host=getattr(a, "host", "0.0.0.0"),
                    port=getattr(a, "port", 8000), log_level="warning")
    elif a.cmd == "add":
        from .db import DB
        DB(Path(a.data) / "clipauto.db").add_streamer(a.platform, a.channel)
        print("ajouté")
    elif a.cmd == "live":
        import aiohttp
        from .config import Streamer
        from .db import DB
        from .monitor import LiveMonitor
        rows = DB(Path(a.data) / "clipauto.db").streamers()

        async def go():
            async with aiohttp.ClientSession() as s:
                res = await LiveMonitor([Streamer(r["platform"], r["channel"]) for r in rows], 0,
                                        None, None).check_once(s)
            for k, v in res.items():
                print(("🔴 " if v else "⚫ ") + k, v or "")
        asyncio.run(go())


if __name__ == "__main__":
    main()
