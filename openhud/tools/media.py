"""Media tools exposed to the chat agent (image, audio, video, jobs).

Every tool reports real provider results. When a provider is unavailable the
tool returns an explicit error; it never claims media was produced.
"""
from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext, ToolResult


def _runtime():
    from ..core.runtime import runtime

    return runtime


class GenerateImageTool(Tool):
    name = "generate_image"
    description = (
        "Gera uma imagem a partir de um texto usando um provider real "
        "(Pollinations sem chave por padrão). Retorna o caminho do arquivo ou um erro honesto."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "width": {"type": "integer", "default": 1024},
            "height": {"type": "integer", "default": 1024},
        },
        "required": ["prompt"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        res = _runtime().images.generate(
            args["prompt"], width=int(args.get("width", 1024)), height=int(args.get("height", 1024)),
        )
        if not res.get("ok"):
            return ToolResult(False, res.get("error", "Falha ao gerar imagem"), {"attempts": res.get("attempts")})
        return ToolResult(True, f"Imagem gerada por {res['provider']}: {res['path']}",
                          {"path": res["path"], "url": res.get("url")})


class NarrateAudioTool(Tool):
    name = "narrate_audio"
    description = "Sintetiza narração em voz real (Edge TTS) a partir de um texto e salva um MP3."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "voice": {"type": "string", "default": "pt-BR-FranciscaNeural"},
            "style": {"type": "string", "default": "narrador"},
        },
        "required": ["text"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        res = _runtime().audio.narrate(
            args["text"], voice=args.get("voice", "pt-BR-FranciscaNeural"),
            style=args.get("style", "narrador"),
        )
        if not res.get("ok"):
            return ToolResult(False, res.get("error", "Falha na narração"), {"attempts": res.get("attempts")})
        return ToolResult(True, f"Narração gerada por {res['provider']}: {res['path']}", {"path": res["path"]})


class RenderVideoTool(Tool):
    name = "render_video"
    description = (
        "Enfileira a renderização real de um vídeo (slideshow de imagens + narração) via ffmpeg. "
        "Retorna o job_id para acompanhar o progresso. Requer ffmpeg e imagens locais."
    )
    parameters = {
        "type": "object",
        "properties": {
            "script": {"type": "string"},
            "images": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["script"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        rt = _runtime()
        images = args.get("images") or []
        job = rt.job_queue.submit("video", {"script": args["script"], "images": images})
        return ToolResult(True, f"Vídeo enfileirado (job {job['id']}). Acompanhe com job_status.",
                          {"job_id": job["id"]})


class JobStatusTool(Tool):
    name = "job_status"
    description = "Consulta o status e o progresso real de um job (vídeo, lote, etc.)."
    parameters = {
        "type": "object",
        "properties": {"job_id": {"type": "string"}},
        "required": ["job_id"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        job = _runtime().jobs.get(args["job_id"])
        if not job:
            return ToolResult(False, "Job não encontrado")
        return ToolResult(True, f"Job {job['id']}: {job['status']} {job['progress']}%"
                                + (f" — erro: {job['error']}" if job.get("error") else ""),
                          {"job": job})


class SpeakTool(Tool):
    name = "speak"
    description = (
        "Converte texto em fala usando a cadeia de TTS configurada (Edge neural por padrão). "
        "Útil para respostas faladas; retorna o áudio em base64 quando bem-sucedido."
    )
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        import base64

        res = _runtime().voice.speak(args["text"])
        if not res.get("ok"):
            return ToolResult(False, res.get("error", "Falha ao sintetizar voz"), {"attempts": res.get("attempts")})
        b64 = base64.b64encode(res["audio"]).decode("ascii")
        return ToolResult(True, f"Áudio gerado por {res['provider']} ({len(res['audio'])} bytes).",
                          {"audio_base64": b64, "mime": res["mime"]})


def build_media_tools() -> list[Tool]:
    return [GenerateImageTool(), NarrateAudioTool(), RenderVideoTool(), JobStatusTool(), SpeakTool()]
