"""Text-to-speech provider chain.

Providers are tried in order; the first that produces audio wins. Every
attempt is reported (ok/failed + reason) so the UI never shows a silent
"no response": if all providers fail, the caller gets the real reasons.

Providers:
* ``edge``   — Microsoft Edge neural voices via the ``edge-tts`` package
               (free, no key). Real synthesis; the default.
* ``browser``— the Web Speech API in the user's browser. No server work; the
               server reports it as available so the UI can speak locally.
* ``openai`` — OpenAI-compatible ``/audio/speech``. Requires a key.

``say``/``espeak`` are reported as unavailable when the binaries are missing
instead of pretending to work.
"""
from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from typing import Any

from .languages import STYLE_PRESETS


@dataclass
class TTSResult:
    ok: bool
    audio: bytes | None = None
    mime: str = "audio/mpeg"
    provider: str = ""
    attempts: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


def _edge_available() -> bool:
    try:
        import edge_tts  # noqa: F401

        return True
    except Exception:
        return False


def _bin_available(name: str) -> bool:
    return shutil.which(name) is not None


def provider_status(secret_lookup=None) -> list[dict[str, Any]]:
    """Report each TTS provider's real availability."""
    out = [
        {"name": "edge", "label": "Microsoft Edge (neural)", "available": _edge_available(),
         "requires_key": False, "kind": "server"},
        {"name": "browser", "label": "Navegador (Web Speech)", "available": True,
         "requires_key": False, "kind": "client"},
    ]
    has_openai = False
    if secret_lookup:
        try:
            has_openai = bool(secret_lookup("openai"))
        except Exception:
            has_openai = False
    out.append({"name": "openai", "label": "OpenAI (audio/speech)", "available": has_openai,
                "requires_key": True, "kind": "server"})
    for binary, label in (("say", "macOS say"), ("espeak-ng", "eSpeak NG")):
        out.append({"name": binary, "label": label, "available": _bin_available(binary),
                    "requires_key": False, "kind": "server"})
    return out


def synthesize(
    text: str,
    *,
    voice: str,
    style: str = "natural",
    rate: str = "",
    pitch: str = "",
    provider: str = "auto",
    openai_key: str | None = None,
    openai_base_url: str = "https://api.openai.com/v1",
    model: str = "tts-1",
) -> TTSResult:
    """Synthesize ``text`` with the first working provider."""
    preset = STYLE_PRESETS.get(style, STYLE_PRESETS["natural"])
    rate = rate or preset["rate"]
    pitch = pitch or preset["pitch"]

    attempts: list[dict[str, Any]] = []
    order = ["edge", "openai"] if provider == "auto" else [provider]
    if provider == "auto" and not _edge_available() and not openai_key:
        order = ["openai"]

    for name in order:
        if name == "edge":
            if not _edge_available():
                attempts.append({"provider": "edge", "ok": False,
                                 "error": "pacote edge-tts não instalado (pip install edge-tts)"})
                continue
            try:
                audio = _edge_synth(text, voice, rate, pitch)
                attempts.append({"provider": "edge", "ok": True, "bytes": len(audio)})
                return TTSResult(True, audio, "audio/mpeg", "edge", attempts)
            except Exception as exc:
                attempts.append({"provider": "edge", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        elif name == "openai":
            if not openai_key:
                attempts.append({"provider": "openai", "ok": False, "error": "sem chave da OpenAI configurada"})
                continue
            try:
                audio = _openai_synth(text, voice, model, openai_key, openai_base_url)
                attempts.append({"provider": "openai", "ok": True, "bytes": len(audio)})
                return TTSResult(True, audio, "audio/mpeg", "openai", attempts)
            except Exception as exc:
                attempts.append({"provider": "openai", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        else:
            attempts.append({"provider": name, "ok": False, "error": "provider desconhecido"})

    return TTSResult(False, None, "audio/mpeg", "", attempts,
                     "Nenhum provider de voz conseguiu sintetizar o texto.")


def _edge_synth(text: str, voice: str, rate: str, pitch: str) -> bytes:
    import edge_tts

    async def _run() -> bytes:
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        buf = bytearray()
        async for chunk in comm.stream():
            if chunk.get("type") == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)

    return asyncio.run(_run())


def _openai_synth(text: str, voice: str, model: str, key: str, base_url: str) -> bytes:
    import httpx

    resp = httpx.post(
        f"{base_url.rstrip('/')}/audio/speech",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "voice": voice or "alloy", "input": text},
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.content
