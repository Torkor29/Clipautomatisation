"""CLI : python -m clipauto run | live | approve <id> | reject <id> | pending"""
from __future__ import annotations

import argparse
import asyncio
import logging

from .config import Config


def main() -> None:
    ap = argparse.ArgumentParser(prog="clipauto")
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="lance la surveillance + clipping")
    sub.add_parser("live", help="affiche qui est en live maintenant")
    sub.add_parser("pending", help="liste les clips à valider")
    for c in ("approve", "reject"):
        sub.add_parser(c).add_argument("id", type=int)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.load(a.config)

    if a.cmd == "run":
        from .app import App
        asyncio.run(App(cfg).run())
    elif a.cmd == "live":
        import aiohttp
        from .monitor import LiveMonitor

        async def go():
            async with aiohttp.ClientSession() as s:
                res = await LiveMonitor(cfg.streamers, 0, None, None).check_once(s)
            for k, v in res.items():
                print(("🔴 " if v else "⚫ ") + k, v or "")
        asyncio.run(go())
    else:
        from .app import App
        app = App(cfg)
        if a.cmd == "pending":
            for r in app.store.pending():
                print(r["id"], r["streamer"], r["score"], r["path"])
        else:
            asyncio.run(app.on_decision(a.id, a.cmd == "approve"))


if __name__ == "__main__":
    main()
