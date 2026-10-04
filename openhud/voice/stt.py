"""Speech-to-text.

Primary path: the browser's Web Speech API transcribes audio locally and
posts only the resulting text — no audio leaves the device, which is the
privacy-preserving default. The server exposes the language catalogue and
stores transcripts only when the user opts in.

Server-side transcription is available when ``faster-whisper`` (or
``openai-whisper``) is installed; the module reports its real availability so
the UI can fall back to the browser instead of pretending to transcribe.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Any

from .languages import resolve_language


@dataclass
class STTResult:
    ok: bool
    text: str = ""
    language: str = ""
    provider: str = ""
    attempts: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


def _whisper_available() -> str | None:
    try:
        import faster_whisper  # noqa: F401

        return "faster-whisper"
    except Exception:
        pass
    try:
        import whisper  # noqa: F401

        return "whisper"
    except Exception:
        return None


def provider_status() -> list[dict[str, Any]]:
    """Report real STT availability (browser STT always available client-side)."""
    local = _whisper_available()
    return [
        {"name": "browser", "label": "Navegador (Web Speech, local)", "available": True,
         "requires_key": False, "kind": "client"},
        {"name": local or "whisper", "label": "Whisper local",
         "available": bool(local), "requires_key": False, "kind": "server"},
        {"name": "openai", "label": "OpenAI (audio/transcriptions)",
         "available": bool(shutil.which("ffmpeg")), "requires_key": True, "kind": "server"},
    ]


def transcribe(audio: bytes, *, language: str | None = None, provider: str = "auto",
               model_size: str = "base", openai_key: str | None = None,
               openai_base_url: str = "https://api.openai.com/v1") -> STTResult:
    """Transcribe ``audio`` bytes. Reports honest failure when unavailable."""
    attempts: list[dict[str, Any]] = []
    lang = resolve_language(language)
    lang_code = lang.code.split("-")[0] if lang else None

    local = _whisper_available()
    order = ["whisper", "openai"] if provider == "auto" else [provider]
    if provider == "auto" and not local and not openai_key:
        order = ["openai"]

    for name in order:
        if name == "whisper":
            if not local:
                attempts.append({"provider": "whisper", "ok": False,
                                 "error": "transcrição local indisponível (pip install faster-whisper)"})
                continue
            try:
                text = _whisper_transcribe(audio, local, model_size, lang_code)
                attempts.append({"provider": local, "ok": True})
                return STTResult(True, text, lang.code if lang else "", local, attempts)
            except Exception as exc:
                attempts.append({"provider": local, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        elif name == "openai":
            if not openai_key:
                attempts.append({"provider": "openai", "ok": False, "error": "sem chave da OpenAI configurada"})
                continue
            try:
                text = _openai_transcribe(audio, lang_code, openai_key, openai_base_url)
                attempts.append({"provider": "openai", "ok": True})
                return STTResult(True, text, lang.code if lang else "", "openai", attempts)
            except Exception as exc:
                attempts.append({"provider": "openai", "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    return STTResult(False, "", lang.code if lang else "", "", attempts,
                     "Nenhum provider de transcrição disponível. Use o microfone do navegador.")


def _whisper_transcribe(audio: bytes, backend: str, model_size: str, lang_code: str | None) -> str:
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".webm", delete=True) as tmp:
        tmp.write(audio)
        tmp.flush()
        if backend == "faster-whisper":
            from faster_whisper import WhisperModel

            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            segments, _ = model.transcribe(tmp.name, language=lang_code)
            return " ".join(seg.text.strip() for seg in segments).strip()
        import whisper  # type: ignore

        model = whisper.load_model(model_size)
        result = model.transcribe(tmp.name, language=lang_code)
        return (result.get("text") or "").strip()


def _openai_transcribe(audio: bytes, lang_code: str | None, key: str, base_url: str) -> str:
    import httpx

    files = {"file": ("audio.webm", audio, "audio/webm")}
    data = {"model": "whisper-1"}
    if lang_code:
        data["language"] = lang_code
    resp = httpx.post(
        f"{base_url.rstrip('/')}/audio/transcriptions",
        headers={"Authorization": f"Bearer {key}"},
        files=files, data=data, timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return (resp.json().get("text") or "").strip()
