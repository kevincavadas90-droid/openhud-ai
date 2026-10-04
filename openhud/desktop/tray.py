"""System-tray UI for the OpenHUD desktop app.

Builds the icon and menu, and drives the :class:`AgentRuntime`. The tray uses
pystray when available and falls back to a console loop otherwise. The menu
shows the live connection status ("OpenHUD conectado" / "OpenHUD desconectado"),
opens the interface, opens Settings, runs diagnostics, connects/disconnects and
quits. Everything here is best-effort and never raises to the caller.
"""
from __future__ import annotations

import threading
import webbrowser
from typing import Any

from .config import DesktopConfig
from .runtime import AgentRuntime

APP_NAME = "OpenHUD AI"


def make_icon_image():
    """Create the tray icon image with Pillow. Returns None if unavailable."""
    try:
        from PIL import Image, ImageDraw
    except Exception:  # noqa: BLE001
        return None
    img = Image.new("RGB", (64, 64), "#0b0e14")
    d = ImageDraw.Draw(img)
    # A diamond matching the site logo.
    d.polygon([(32, 8), (56, 32), (32, 56), (8, 32)], outline="#6c8cff", width=5)
    d.ellipse((24, 24, 40, 40), fill="#9d7bff")
    return img


class TrayApp:
    def __init__(self, config: DesktopConfig, runtime: AgentRuntime,
                 local_url: str | None = None, on_diagnose=None) -> None:
        self.config = config
        self.runtime = runtime
        self.local_url = local_url
        self.on_diagnose = on_diagnose
        self._icon = None
        self._icon_title = APP_NAME

    def _title(self) -> str:
        return f"{APP_NAME} — {self.runtime.status_label()}"

    # -- menu actions ----------------------------------------------------
    def open_interface(self, *_args) -> None:
        if self.local_url:
            webbrowser.open(self.local_url)
        elif self.config.server:
            webbrowser.open(self.config.server)

    def open_settings(self, *_args) -> None:
        # Settings live in the web UI; open the app at the settings view.
        base = self.local_url or self.config.server
        if base:
            webbrowser.open(base.rstrip("/") + "/settings")

    def toggle_connection(self, *_args) -> None:
        if self.runtime.is_running():
            self.runtime.stop()
        else:
            self.runtime.start()
        self._refresh()

    def run_diagnostics(self, *_args) -> None:
        if self.on_diagnose:
            self.on_diagnose()

    def _refresh(self) -> None:
        if self._icon is not None:
            try:
                self._icon.title = self._title()
            except Exception:  # noqa: BLE001
                pass

    # -- run -------------------------------------------------------------
    def run(self) -> None:
        """Run the tray. Falls back to a console loop if pystray is missing."""
        try:
            import pystray  # type: ignore
        except Exception as exc:  # noqa: BLE001
            print(f"[OpenHUD] bandeja indisponível ({exc}). Rodando no console. Ctrl+C para sair.")
            self._console_loop()
            return

        image = make_icon_image()
        if image is None:
            print("[OpenHUD] Pillow indisponível; rodando no console.")
            self._console_loop()
            return

        def _state_cb(state: str, detail: str) -> None:
            self._refresh()

        self.runtime._on_state = _state_cb  # reflect state changes in the title

        menu = pystray.Menu(
            pystray.MenuItem(lambda item: self.runtime.status_label(), None, enabled=False),
            pystray.MenuItem("Abrir interface", self.open_interface, default=True),
            pystray.MenuItem("Configurações", self.open_settings),
            pystray.MenuItem("Diagnóstico", self.run_diagnostics),
            pystray.MenuItem(
                lambda item: "Desconectar" if self.runtime.is_running() else "Conectar",
                self.toggle_connection,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", self._quit),
        )
        self._icon = pystray.Icon("OpenHUD", image, self._title(), menu=menu)
        self.runtime.start()
        self._icon.run()

    def _quit(self, icon=None, *_args) -> None:
        try:
            self.runtime.stop()
        except Exception:  # noqa: BLE001
            pass
        if icon is not None:
            try:
                icon.stop()
            except Exception:  # noqa: BLE001
                pass
        import os

        os._exit(0)

    def _console_loop(self) -> None:
        self.runtime.start()
        print(f"[OpenHUD] {self.runtime.status_label()}. Ctrl+C para sair.")
        try:
            while True:
                threading.Event().wait(1)
        except KeyboardInterrupt:
            self.runtime.stop()
