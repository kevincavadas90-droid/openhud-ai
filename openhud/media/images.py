"""Image generation.

Real providers only. ``pollinations`` (keyless) is used by default and was
verified to return a real JPEG. ``openai`` uses ``/images/generations`` when a
key is configured. When no provider can run, the service returns an explicit
error — it never claims an image was created.

Generated files are written to the workspace under ``generated/images``.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote


class ImageService:
    def __init__(self, workspace_dir: Path, secret_lookup=None) -> None:
        self.dir = Path(workspace_dir) / "generated" / "images"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._secret = secret_lookup

    def providers(self) -> list[dict[str, Any]]:
        return [
            {"name": "pollinations", "label": "Pollinations (keyless)", "available": True,
             "requires_key": False},
            {"name": "openai", "label": "OpenAI (images)", "requires_key": True,
             "available": bool(self._secret and self._secret("openai"))},
        ]

    def generate(self, prompt: str, *, width: int = 1024, height: int = 1024,
                 provider: str = "auto", model: str = "flux", seed: int | None = None,
                 conversation_id: str | None = None) -> dict[str, Any]:
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "Prompt vazio."}
        attempts: list[dict[str, Any]] = []
        order = ["pollinations", "openai"] if provider == "auto" else [provider]

        for name in order:
            if name == "pollinations":
                try:
                    data = self._pollinations(prompt, width, height, model, seed)
                    path = self._save(data, "jpg", conversation_id)
                    attempts.append({"provider": "pollinations", "ok": True, "bytes": len(data)})
                    return {"ok": True, "provider": "pollinations", "path": str(path),
                            "url": f"/api/media/file?path={quote(str(path.relative_to(self.dir.parent.parent)))}",
                            "attempts": attempts}
                except Exception as exc:
                    attempts.append({"provider": "pollinations", "ok": False,
                                     "error": f"{type(exc).__name__}: {exc}"})
            elif name == "openai":
                key = self._secret("openai") if self._secret else None
                if not key:
                    attempts.append({"provider": "openai", "ok": False, "error": "sem chave da OpenAI"})
                    continue
                try:
                    data = self._openai(prompt, width, height, key)
                    path = self._save(data, "png", conversation_id)
                    attempts.append({"provider": "openai", "ok": True, "bytes": len(data)})
                    return {"ok": True, "provider": "openai", "path": str(path),
                            "url": f"/api/media/file?path={quote(str(path.relative_to(self.dir.parent.parent)))}",
                            "attempts": attempts}
                except Exception as exc:
                    attempts.append({"provider": "openai", "ok": False,
                                     "error": f"{type(exc).__name__}: {exc}"})
            else:
                attempts.append({"provider": name, "ok": False, "error": "provider desconhecido"})

        return {"ok": False, "error": "Nenhum provider de imagem conseguiu gerar a imagem.",
                "attempts": attempts}

    def _pollinations(self, prompt: str, w: int, h: int, model: str, seed: int | None) -> bytes:
        import httpx

        url = (
            f"https://image.pollinations.ai/prompt/{quote(prompt)}"
            f"?width={w}&height={h}&nologo=true&model={quote(model)}"
        )
        if seed is not None:
            url += f"&seed={int(seed)}"
        resp = httpx.get(url, timeout=90, follow_redirects=True)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        ctype = resp.headers.get("content-type", "")
        if not ctype.startswith("image/"):
            raise RuntimeError(f"resposta não é imagem ({ctype})")
        if len(resp.content) < 500:
            raise RuntimeError("resposta de imagem muito pequena")
        return resp.content

    def _openai(self, prompt: str, w: int, h: int, key: str) -> bytes:
        import httpx

        resp = httpx.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "gpt-image-1", "prompt": prompt, "size": f"{w}x{h}", "n": 1},
            timeout=120,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        item = (resp.json().get("data") or [{}])[0]
        if item.get("b64_json"):
            import base64

            return base64.b64decode(item["b64_json"])
        if item.get("url"):
            img = httpx.get(item["url"], timeout=90)
            return img.content
        raise RuntimeError("resposta sem imagem")

    def _save(self, data: bytes, ext: str, conversation_id: str | None) -> Path:
        name = f"{int(time.time())}-{uuid.uuid4().hex[:8]}.{ext}"
        path = self.dir / name
        path.write_bytes(data)
        return path
