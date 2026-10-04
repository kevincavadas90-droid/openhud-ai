"""Voice subsystem: speech-to-text, text-to-speech and language support."""
from .languages import LANGUAGES, VOICE_STYLES, list_languages
from .service import VoiceService, VoiceSettings

__all__ = ["VoiceService", "VoiceSettings", "LANGUAGES", "VOICE_STYLES", "list_languages"]
