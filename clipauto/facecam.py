"""Détection automatique de la facecam (OpenCV, local) pour le format « cam + jeu »."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)
try:  # importé une fois au démarrage (l'import depuis un thread secondaire peut échouer)
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


def _frames(path: Path, n: int = 8, w: int = 640) -> list[np.ndarray]:
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(path)], capture_output=True, text=True).stdout.strip() or 0)
    out = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                              "-vf", f"scale={w}:-2", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
                             capture_output=True).stdout
        if raw:
            out.append(np.frombuffer(raw, np.uint8).reshape(-1, w))
    return out


def detect(path: Path) -> dict | None:
    """Renvoie {"face": rect, "facecam": rect, "full_cam": bool} en fractions 0-1, ou None."""
    if cv2 is None:
        log.warning("opencv absent : détection facecam indisponible")
        return None
    try:
        return _detect(path)
    except Exception:
        log.exception("détection facecam")
        return None


def _detect(path: Path) -> dict | None:
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    boxes = []
    for f in _frames(path):
        h, w = f.shape
        faces = casc.detectMultiScale(f, scaleFactor=1.1, minNeighbors=6, minSize=(w // 40, w // 40))
        for (x, y, fw, fh) in faces:
            boxes.append((x / w, y / h, fw / w, fh / h))
    if not boxes:
        return None
    # visage le plus souvent présent au même endroit (une facecam ne bouge pas)
    arr = np.array(boxes)
    centers = arr[:, :2] + arr[:, 2:] / 2
    best, cnt = 0, -1
    for i, c in enumerate(centers):
        k = int(np.sum(np.linalg.norm(centers - c, axis=1) < 0.06))
        if k > cnt:
            best, cnt = i, k
    near = arr[np.linalg.norm(centers - centers[best], axis=1) < 0.06]
    x, y, fw, fh = np.median(near, axis=0)
    full_cam = fw > 0.12  # gros visage = stream « IRL / juste chatting », pas une petite cam
    # la facecam = zone autour du visage (épaules comprises), ratio 16:9 environ
    cw, ch = min(fw * 3.4, 1.0), min(fh * 3.0, 1.0)
    cx, cy = x + fw / 2, y + fh / 2 + fh * 0.35
    rect = {"x": float(np.clip(cx - cw / 2, 0, 1 - cw)), "y": float(np.clip(cy - ch / 2, 0, 1 - ch)),
            "w": float(cw), "h": float(ch)}
    return {"face": {"x": float(x), "y": float(y), "w": float(fw), "h": float(fh)}, "facecam": rect,
            "full_cam": bool(full_cam), "hits": int(cnt)}
