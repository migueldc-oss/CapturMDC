"""System tray icon (pystray) with Spanish menu actions for CapturMDC."""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw

MENU_FULL = "Captura completa"
MENU_PARTIAL = "Captura parcial"
MENU_SETTINGS = "Configuración"
MENU_PAUSE = "Pausar/Reanudar"
MENU_QUIT = "Salir"

ICON_SIZE = 32
ACCENT = "#4fb3ff"
ACCENT_PAUSED = "#ffb84f"
DARK = "#0b1320"

ActionCallback = Callable[[str], None]


def build_icon_image(paused: bool = False) -> Image.Image:
    """Draw a small camera icon; amber when paused."""
    image = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    accent = ACCENT_PAUSED if paused else ACCENT

    draw.rounded_rectangle((4, 10, 28, 26), radius=4, fill=accent)
    draw.rectangle((8, 6, 16, 11), fill=accent)
    draw.ellipse((12, 13, 22, 23), fill=DARK)
    draw.ellipse((15, 16, 19, 20), fill=accent)

    if paused:
        draw.rectangle((24, 6, 26, 12), fill="#ffffff")
        draw.rectangle((28, 6, 30, 12), fill="#ffffff")
    return image


class TrayIcon:
    """pystray icon whose actions are forwarded to a thread-safe action queue."""

    def __init__(
        self,
        on_action: ActionCallback,
        is_paused: Optional[Callable[[], bool]] = None,
        title: str = "CapturMDC",
    ) -> None:
        self._on_action = on_action
        self._is_paused = is_paused or (lambda: False)
        self._title = title

        self.menu = pystray.Menu(
            pystray.MenuItem(MENU_FULL, self._handler(MENU_FULL, "capture_full")),
            pystray.MenuItem(MENU_PARTIAL, self._handler(MENU_PARTIAL, "capture_partial")),
            pystray.MenuItem(MENU_SETTINGS, self._handler(MENU_SETTINGS, "open_settings"), default=True),
            pystray.MenuItem(
                MENU_PAUSE,
                self._handler(MENU_PAUSE, "toggle_pause"),
                checked=lambda item: bool(self._is_paused()),
            ),
            pystray.MenuItem(MENU_QUIT, self._handler(MENU_QUIT, "quit")),
        )

        self.icon = pystray.Icon("CapturMDC", build_icon_image(False), title, self.menu)

    def _handler(self, _text: str, action: str) -> Callable[..., None]:
        def _activate(icon: pystray.Icon, item: pystray.MenuItem = None) -> None:
            self._on_action(action)

        return _activate

    # ------------------------------------------------------------------ lifecycle
    def start(self, timeout: float = 2.0) -> None:
        thread = threading.Thread(target=self.icon.run, name="CapturMDC-tray", daemon=True)
        thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.icon.visible:
                break
            time.sleep(0.05)

    def refresh(self) -> None:
        """Rebuild icon art, tooltip and menu so pause state is reflected."""
        paused = bool(self._is_paused())
        try:
            self.icon.icon = build_icon_image(paused)
            self.icon.title = f"{self._title} (pausa)" if paused else self._title
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            self.icon.update_menu()
        except Exception:  # pragma: no cover - defensive
            pass

    def notify(self, message: str, title: Optional[str] = None) -> None:
        try:
            self.icon.notify(message, title)
        except Exception:  # pragma: no cover - notifications are best-effort
            pass

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:  # pragma: no cover - defensive
            pass
