"""Voice service: configuration, synthesis, transcription and privacy.

Voice settings live in the settings store (``voice_*`` keys). Transcripts are
only persisted when the user enables ``voice_save_transcript``; audio is never
stored by default (the browser sends text, not audio, in the normal path).

Voice never grants permissions: speaking a command is equivalent to typing
it. Financial/PC actions still pass through the same gates as text.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import stt as stt_mod
from . import tts as tts_mod
from .languages import VOICE_STYLES, list_languages, resolve_language

VOICE_DEFAULTS: dict[str, Any] = {
    "voice_enabled": True,
    "voice_language": "pt-BR",          # or "auto"
    "voice_style": "natural",
    "voice_rate": "",                   # e.g. "+10%"
    "voice_pitch": "",                  # e.g. "+5Hz"
    "voice_provider": "auto",           # auto | edge | openai
    "voice_continuous": False,          # continuous conversation mode
    "voice_wake_word": False,           # optional "OpenHUD" wake word
    "voice_wake_phrase": "OpenHUD",
    "voice_save_audio": False,
    "voice_save_transcript": False,
    "voice_save_history": False,
    "voice_tts_voice": "",              # override the language default voice
}


@dataclass
class VoiceSettings:
    enabled: bool = True
    language: str = "pt-BR"
    style: str = "natural"
    rate: str = ""
    pitch: str = ""
    provider: str = "auto"
    continuous: bool = False
    wake_word: bool = False
    wake_phrase: str = "OpenHUD"
    save_audio: bool = False
    save_transcript: bool = False
    save_history: bool = False
    voice_override: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VoiceSettings":
        return cls(
            enabled=bool(d.get("voice_enabled", True)),
            language=d.get("voice_language", "pt-BR") or "pt-BR",
            style=d.get("voice_style", "natural"),
            rate=d.get("voice_rate", "") or "",
            pitch=d.get("voice_pitch", "") or "",
            provider=d.get("voice_provider", "auto") or "auto",
            continuous=bool(d.get("voice_continuous", False)),
            wake_word=bool(d.get("voice_wake_word", False)),
            wake_phrase=d.get("voice_wake_phrase", "OpenHUD") or "OpenHUD",
            save_audio=bool(d.get("voice_save_audio", False)),
            save_transcript=bool(d.get("voice_save_transcript", False)),
            save_history=bool(d.get("voice_save_history", False)),
            voice_override=d.get("voice_tts_voice", "") or "",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "voice_enabled": self.enabled,
            "voice_language": self.language,
            "voice_style": self.style,
            "voice_rate": self.rate,
            "voice_pitch": self.pitch,
            "voice_provider": self.provider,
            "voice_continuous": self.continuous,
            "voice_wake_word": self.wake_word,
            "voice_wake_phrase": self.wake_phrase,
            "voice_save_audio": self.save_audio,
            "voice_save_transcript": self.save_transcript,
            "voice_save_history": self.save_history,
            "voice_tts_voice": self.voice_override,
        }


class VoiceService:
    def __init__(self, db, secret_lookup=None) -> None:
        self.db = db
        self._secret = secret_lookup

    # -- settings --------------------------------------------------------
    def settings(self) -> VoiceSettings:
        stored = self.db.get_setting("voice_config") or {}
        merged = dict(VOICE_DEFAULTS)
        merged.update(stored)
        return VoiceSettings.from_dict(merged)

    def update(self, patch: dict[str, Any]) -> VoiceSettings:
        current = self.settings().to_dict()
        for k, v in patch.items():
            if k in VOICE_DEFAULTS:
                current[k] = v
        self.db.set_setting("voice_config", current)
        return self.settings()

    # -- status ----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        s = self.settings()
        return {
            "enabled": s.enabled,
            "continuous": s.continuous,
            "wake_word": s.wake_word,
            "wake_phrase": s.wake_phrase,
            "config": s.to_dict(),
            "privacy": {
                "save_audio": s.save_audio,
                "save_transcript": s.save_transcript,
                "save_history": s.save_history,
            },
            "languages": list_languages(),
            "styles": VOICE_STYLES,
            "tts_providers": tts_mod.provider_status(self._secret),
            "stt_providers": stt_mod.provider_status(),
        }

    # -- synthesis -------------------------------------------------------
    def speak(self, text: str) -> dict[str, Any]:
        """Return a dict with audio bytes + provider info, or an honest error."""
        s = self.settings()
        if not s.enabled:
            return {"ok": False, "error": "A voz está desativada nas configurações.", "attempts": []}
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "Texto vazio.", "attempts": []}
        lang = resolve_language(s.language)
        voice = s.voice_override or (lang.voice if lang else "pt-BR-FranciscaNeural")
        openai_key = self._secret("openai") if self._secret else None
        result = tts_mod.synthesize(
            text, voice=voice, style=s.style, rate=s.rate, pitch=s.pitch,
            provider=s.provider, openai_key=openai_key,
        )
        out = {
            "ok": result.ok,
            "provider": result.provider,
            "mime": result.mime,
            "attempts": result.attempts,
            "error": result.error,
        }
        if result.ok:
            out["audio"] = result.audio
        if s.save_transcript or s.save_history:
            self.db.add_voice_history(text, s.language, "tts")
        return out

    # -- transcription (server-side; browser path posts text directly) ---
    def transcribe(self, audio: bytes, language: str | None = None,
                   conversation_id: str | None = None) -> dict[str, Any]:
        s = self.settings()
        openai_key = self._secret("openai") if self._secret else None
        result = stt_mod.transcribe(audio, language=language or s.language,
                                    provider="auto", openai_key=openai_key)
        if result.ok and (s.save_transcript or s.save_history):
            self.db.add_voice_history(result.text, result.language, "stt", conversation_id)
        return {
            "ok": result.ok, "text": result.text, "language": result.language,
            "provider": result.provider, "attempts": result.attempts, "error": result.error,
        }

    def record_transcript(self, text: str, language: str = "",
                          conversation_id: str | None = None) -> dict[str, Any] | None:
        """Persist a browser-produced transcript when the user opted in."""
        s = self.settings()
        if not (s.save_transcript or s.save_history):
            return None
        return self.db.add_voice_history(text, language or s.language, "stt", conversation_id)

    def history(self, conversation_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        return self.db.list_voice_history(conversation_id, limit)

    def clear_history(self, vid: str | None = None) -> int:
        return self.db.delete_voice_history(vid)
