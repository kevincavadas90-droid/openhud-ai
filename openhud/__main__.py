"""Entry point: ``python -m openhud`` starts the web server."""
from __future__ import annotations

import uvicorn

from .config import settings


def main() -> None:
    uvicorn.run("openhud.web.app:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
