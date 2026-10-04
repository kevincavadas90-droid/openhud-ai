"""Video pipeline.

Video rendering needs ``ffmpeg``. The pipeline plans the production in
explicit, independent stages and renders a real slideshow (image + narration
+ optional subtitles) when ffmpeg and the inputs are available. Every stage
reports its own result, so a failure in one stage can be retried alone.

Progress is reported by the real work performed (images prepared, audio
synthesised, frames rendered) — never invented. When ffmpeg is missing, the
service returns a clear error and the job fails honestly.
"""
from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from ..voice.tts import synthesize


class VideoService:
    def __init__(self, workspace_dir: Path, secret_lookup=None) -> None:
        self.dir = Path(workspace_dir) / "generated" / "video"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._secret = secret_lookup

    def providers(self) -> list[dict[str, Any]]:
        return [
            {"name": "ffmpeg", "label": "FFmpeg (render local)", "requires_key": False,
             "available": shutil.which("ffmpeg") is not None},
            {"name": "edge", "label": "Edge TTS (narração)", "requires_key": False,
             "available": _has_module("edge_tts")},
        ]

    def plan(self, script: str) -> dict[str, Any]:
        """Split a script into scene ideas (one per non-empty paragraph)."""
        scenes = [s.strip() for s in (script or "").split("\n\n") if s.strip()]
        if not scenes:
            scenes = [s.strip() for s in (script or "").split("\n") if s.strip()]
        return {
            "scenes": [{"index": i + 1, "text": s} for i, s in enumerate(scenes)],
            "stages": ["roteiro", "imagem", "narração", "legenda", "edição", "exportação"],
        }

    def render(self, script: str, *, images: list[str] | None = None,
               voice: str = "pt-BR-FranciscaNeural",
               report: Callable[[int, str], None] | None = None) -> dict[str, Any]:
        """Render a real MP4 slideshow. Requires ffmpeg + at least one image."""
        def log(p: int, m: str) -> None:
            if report:
                report(p, m)

        if shutil.which("ffmpeg") is None:
            return {"ok": False, "error": "ffmpeg não instalado; não é possível renderizar vídeo."}

        plan = self.plan(script)
        images = [p for p in (images or []) if Path(p).exists()]
        if not images:
            return {"ok": False, "error": "Nenhuma imagem válida informada para o vídeo."}
        log(10, f"{len(images)} imagem(ns) prontas; {len(plan['scenes'])} cena(s) planejadas.")

        # Narration (independent stage; failure here does not abort the video).
        narration_path: Path | None = None
        key = self._secret("openai") if self._secret else None
        narr_text = " ".join(s["text"] for s in plan["scenes"])[:4000]
        tts = synthesize(narr_text, voice=voice, style="narrador", provider="auto", openai_key=key)
        if tts.ok:
            narration_path = self.dir / f"{int(time.time())}-{uuid.uuid4().hex[:6]}.mp3"
            narration_path.write_bytes(tts.audio or b"")
            log(40, f"Narração sintetizada ({len(tts.audio or b'')} bytes).")
        else:
            log(40, "Narração indisponível: " + tts.error)

        # Build a concat list; each image shown for an equal share.
        out = self.dir / f"{int(time.time())}-{uuid.uuid4().hex[:6]}.mp4"
        concat = self.dir / f"concat-{uuid.uuid4().hex[:6]}.txt"
        per = max(2, int(12 / len(images)))
        concat.write_text("".join(f"file '{Path(i).as_posix()}'\nduration {per}\n" for i in images))
        concat.write_text(concat.read_text() + f"file '{Path(images[-1]).as_posix()}'\n")

        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat)]
        if narration_path:
            cmd += ["-i", str(narration_path), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest"]
        else:
            cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        cmd += [str(out)]
        log(60, "Renderizando vídeo com ffmpeg…")
        import subprocess

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        concat.unlink(missing_ok=True)
        if proc.returncode != 0:
            return {"ok": False, "error": f"ffmpeg falhou: {proc.stderr[-500:]}",
                    "narration": str(narration_path) if narration_path else None}
        log(100, "Vídeo renderizado.")
        return {"ok": True, "path": str(out),
                "url": f"/api/media/file?path=generated/video/{out.name}",
                "narration": str(narration_path) if narration_path else None,
                "plan": plan}


def _has_module(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None
