"""Variables d'environnement (.env) et description d'un streamer."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path



def load_dotenv(path: str | Path = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class Streamer:
    platform: str  # twitch | kick | youtube
    channel: str

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.channel.lower()}"

    @property
    def url(self) -> str:
        if self.platform == "twitch":
            return f"https://www.twitch.tv/{self.channel}"
        if self.platform == "kick":
            return f"https://kick.com/{self.channel}"
        if self.platform == "youtube":
            ch = self.channel if self.channel.startswith("@") else f"channel/{self.channel}"
            return f"https://www.youtube.com/{ch}/live"
        raise ValueError(f"plateforme inconnue: {self.platform}")
