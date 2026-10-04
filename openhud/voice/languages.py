"""Language catalogue for STT/TTS.

Each language maps to a BCP-47 tag used by the browser SpeechRecognition API
(STT) and to a default neural voice used by the server-side TTS chain.

The browser handles recognition locally, so STT works for any language the
user's browser supports. Server TTS voices below are real edge-tts voices
(verified against the edge-tts catalogue); adding a language is a matter of
appending one entry.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str          # internal code
    label: str         # human label
    bcp47: str         # browser recognition tag
    voice: str         # default edge-tts voice
    aliases: tuple[str, ...] = ()


LANGUAGES: dict[str, Language] = {
    "pt-BR": Language("pt-BR", "Português (Brasil)", "pt-BR", "pt-BR-FranciscaNeural", ("português", "portugues", "br")),
    "pt-PT": Language("pt-PT", "Português (Portugal)", "pt-PT", "pt-PT-RaquelNeural", ("pt",)),
    "en-US": Language("en-US", "English (US)", "en-US", "en-US-AriaNeural", ("english", "inglês", "ingles", "en")),
    "es-ES": Language("es-ES", "Español", "es-ES", "es-ES-ElviraNeural", ("espanhol", "español", "es")),
    "fr-FR": Language("fr-FR", "Français", "fr-FR", "fr-FR-DeniseNeural", ("francês", "frances", "fr")),
    "de-DE": Language("de-DE", "Deutsch", "de-DE", "de-DE-KatjaNeural", ("alemão", "alemao", "de")),
    "it-IT": Language("it-IT", "Italiano", "it-IT", "it-IT-ElsaNeural", ("italiano", "it")),
    "ja-JP": Language("ja-JP", "日本語", "ja-JP", "ja-JP-NanamiNeural", ("japonês", "japones", "ja")),
    "ko-KR": Language("ko-KR", "한국어", "ko-KR", "ko-KR-SunHiNeural", ("coreano", "ko")),
    "zh-CN": Language("zh-CN", "中文 (简体)", "zh-CN", "zh-CN-XiaoxiaoNeural", ("chinês", "chines", "zh")),
    "ar-SA": Language("ar-SA", "العربية", "ar-SA", "ar-SA-ZariyahNeural", ("árabe", "arabe", "ar")),
    "hi-IN": Language("hi-IN", "हिन्दी", "hi-IN", "hi-IN-SwaraNeural", ("hindi", "hi")),
}

# Named speaking styles. Only applied when the TTS provider supports it;
# otherwise the style is reflected in the text/SSML emphasis.
VOICE_STYLES = [
    "natural", "amigavel", "profissional", "calmo", "animado",
    "serio", "humoristico", "narrador", "professor", "companheiro",
]

# Rate/pitch presets per style (edge-tts accepts e.g. "+10%", "-5Hz").
STYLE_PRESETS: dict[str, dict[str, str]] = {
    "natural": {"rate": "+0%", "pitch": "+0Hz"},
    "amigavel": {"rate": "+3%", "pitch": "+3Hz"},
    "profissional": {"rate": "+0%", "pitch": "-2Hz"},
    "calmo": {"rate": "-10%", "pitch": "-2Hz"},
    "animado": {"rate": "+12%", "pitch": "+8Hz"},
    "serio": {"rate": "-4%", "pitch": "-6Hz"},
    "humoristico": {"rate": "+6%", "pitch": "+6Hz"},
    "narrador": {"rate": "-6%", "pitch": "-4Hz"},
    "professor": {"rate": "-4%", "pitch": "+0Hz"},
    "companheiro": {"rate": "+4%", "pitch": "+2Hz"},
}


def list_languages() -> list[dict]:
    return [
        {"code": lang.code, "label": lang.label, "bcp47": lang.bcp47, "voice": lang.voice}
        for lang in LANGUAGES.values()
    ]


def resolve_language(value: str | None) -> Language | None:
    """Accept a code, a BCP-47 tag or a friendly alias. ``auto``/empty -> None."""
    if not value or value.lower() in ("auto", "detect", "automatico", "automático"):
        return None
    if value in LANGUAGES:
        return LANGUAGES[value]
    low = value.lower()
    for lang in LANGUAGES.values():
        if low == lang.bcp47.lower() or low in lang.aliases or low.split("-")[0] == lang.code.split("-")[0].lower():
            return lang
    return None
