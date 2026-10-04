"""Audio pipeline: TTS narration, transcription and (best-effort) processing.

Narration reuses the real TTS provider chain. Noise removal and format
conversion require ``ffmpeg``; when it is missing those operations report an
explicit "ffmpeg não instalado" error instead of pretending to succeed.
"""
from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from ..voice.tts import synthesize


class AudioService:
    def __init__(self, workspace_dir: Path, secret_lookup=None) -> None:
        self.dir = Path(workspace_dir) / "generated" / "audio"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._secret = secret_lookup

    def providers(self) -> list[dict[str, Any]]:
        return [
            {"name": "edge", "label": "Edge TTS (narração)", "available": _has("edge-tts"),
             "requires_key": False},
            {"name": "ffmpeg", "label": "FFmpeg (processamento)", "available": shutil.which("ffmpeg") is not None,
             "requires_key": False},
        ]

    def narrate(self, text: str, *, voice: str = "pt-BR-FranciscaNeural",
                style: str = "narrador") -> dict[str, Any]:
        key = self._secret("openai") if self._secret else None
        result = synthesize(text, voice=voice, style=style, provider="auto", openai_key=key)
        if not result.ok:
            return {"ok": False, "error": result.error, "attempts": result.attempts}
        path = self.dir / f"{int(time.time())}-{uuid.uuid4().hex[:8]}.mp3"
        path.write_bytes(result.audio or b"")
        return {"ok": True, "provider": result.provider, "path": str(path),
                "url": f"/api/media/file?path=generated/audio/{path.name}",
                "attempts": result.attempts}

    def remove_noise(self, input_path: Path, output_path: Path | None = None) -> dict[str, Any]:
        return self._ffmpeg(
            input_path, output_path,
            ["-af", "afftdn=nf=-25"],
        )

    def convert(self, input_path: Path, fmt: str = "mp3", output_path: Path | None = None) -> dict[str, Any]:
        return self._ffmpeg(input_path, output_path, [])

    def _ffmpeg(self, input_path: Path, output_path: Path | None, extra: list[str]) -> dict[str, Any]:
        if shutil.which("ffmpeg") is None:
            return {"ok": False, "error": "ffmpeg não instalado; não é possível processar áudio."}
        import subprocess

        out = output_path or (self.dir / f"{int(time.time())}-{uuid.uuid4().hex[:6]}.mp3")
        cmd = ["ffmpeg", "-y", "-i", str(input_path), *extra, str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            return {"ok": False, "error": f"ffmpeg falhou: {proc.stderr[-400:]}"}
        return {"ok": True, "path": str(out)}


def _has(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module.replace("-", "_")) is not None
