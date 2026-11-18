"""Chargement de la configuration (config.yaml + variables d'environnement / .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


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


@dataclass
class Config:
    data_dir: Path
    poll_seconds: int
    streamers: list[Streamer]
    record: dict = field(default_factory=dict)
    detect: dict = field(default_factory=dict)
    clip: dict = field(default_factory=dict)
    publish: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path = "config.yaml") -> "Config":
        load_dotenv()
        raw = yaml.safe_load(Path(path).read_text())
        return cls(
            data_dir=Path(raw.get("data_dir", "data")),
            poll_seconds=int(raw.get("poll_seconds", 120)),
            streamers=[Streamer(**s) for s in raw.get("streamers", [])],
            record=raw.get("record", {}),
            detect=raw.get("detect", {}),
            clip=raw.get("clip", {}),
            publish=raw.get("publish", {}),
        )
