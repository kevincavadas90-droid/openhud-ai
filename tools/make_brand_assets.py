"""Generate brand assets for OpenHUD AI (icon + logo PNGs).

Run once to (re)produce the real image files shipped with the app and site:

    python tools/make_brand_assets.py

Writes ``openhud/web/static/site/app-icon.png`` (512px),
``app-icon-256.png`` and ``installer/openhud.ico`` (multi-size Windows icon).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "openhud" / "web" / "static" / "site"


def draw(size: int) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill="#0b0e14")
    pad = s * 0.16
    d.polygon([(s / 2, pad), (s - pad, s / 2), (s / 2, s - pad), (pad, s / 2)],
              outline="#6c8cff", width=max(2, int(s * 0.075)))
    cr = s * 0.16
    d.ellipse((s / 2 - cr, s / 2 - cr, s / 2 + cr, s / 2 + cr), fill="#9d7bff")
    return img


def main() -> int:
    SITE.mkdir(parents=True, exist_ok=True)
    draw(512).save(SITE / "app-icon.png")
    img256 = draw(256)
    img256.save(SITE / "app-icon-256.png")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_path = ROOT / "installer" / "openhud.ico"
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    img256.save(ico_path, format="ICO", sizes=sizes)
    print("wrote app-icon.png, app-icon-256.png, installer/openhud.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
