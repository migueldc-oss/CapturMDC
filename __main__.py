"""CapturMDC entry point: hidden Tk root, action queue, hotkeys, tray, settings."""

from __future__ import annotations

import os
import queue
import sys
import time
from typing import Any, Dict, Optional

# Support both direct script execution and ``python -m CapturMDC``.
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

import customtkinter as ctk

import capture
import config
import hotkeys
import selection
import tray
from settings import SettingsWindow

POLL_MS = 120

BLOCKED_MESSAGES = {
    "busy": "Captura en curso, espera a que termine",
    "paused": "Capturas en pausa: usa Pausar/Reanudar en el menú de la bandeja",
    "settings": "Ventana de configuración abierta: los atajos están bloqueados",
    "selection": "Selección parcial en curso",
    "transition": "Cambio de pausa/reanudar en curso",
}


class App:
    """Background tray application with a hidden CTk root and Tk mainloop."""

    def __init__(self) -> None:
        capture.ensure_dpi_aware()

        self.cfg = config.load_config()
        self.cfg["save_path"] = self._prepare_save_dir(self.cfg["save_path"])
        if not os.path.exists(config.config_path()):
            # First run: persist defaults so the file is editable.
            try:
                config.save_config(self.cfg)
            except OSError as exc:
                print(f"CapturMDC: no se pudo escribir config.json ({exc})", file=sys.stderr)

        ctk.set_appearance_mode(str(self.cfg["theme"]))
        self.root = ctk.CTk()
        self.root.title("CapturMDC")
        self.root.withdraw()

        self._queue: queue.Queue[str] = queue.Queue()
        self._exiting = False
        self._busy = False
        self._paused = False
        self._selection_active = False
        self._transition_until = 0.0
        self._blocked_reason: Optional[str] = None
        self._blocked_notify = 0.0
        self.settings: Optional[SettingsWindow] = None

        self.hotkeys = hotkeys.HotkeyController(
            full_hotkey=self.cfg["full_hotkey"],
            partial_hotkey=self.cfg["partial_hotkey"],
            callback=self._post_action,
            allow_action=self._allow_hotkey,
            partial_delay=float(self.cfg["partial_delay"]),
            max_capture_timeout=float(self.cfg["max_capture_timeout"]),
        )
        self.tray = tray.TrayIcon(
            on_action=self._post_action,
            is_paused=lambda: bool(self._paused),
            title="CapturMDC",
        )

    # ------------------------------------------------------------------ plumbing
    def _post_action(self, action: str) -> None:
        if not self._exiting:
            self._queue.put(action)

    def _allow_hotkey(self) -> bool:
        """Hotkeys are ignored while exiting, busy, paused, settings or selection."""
        if self._exiting:
            return False
        reason: Optional[str] = None
        if self._busy:
            reason = "busy"
        elif self._paused:
            reason = "paused"
        elif self.settings is not None:
            reason = "settings"
        elif self._selection_active:
            reason = "selection"
        elif self._in_transition():
            reason = "transition"
        if reason is not None:
            self._notify_blocked(reason)
            return False
        return True

    def _notify_blocked(self, reason: str) -> None:
        """Throttled tray feedback so blocked hotkey presses are not silent."""
        now = time.monotonic()
        if reason == self._blocked_reason and now - self._blocked_notify < 2.5:
            return
        self._blocked_reason = reason
        self._blocked_notify = now
        self.tray.notify(BLOCKED_MESSAGES.get(reason, reason))

    def _allow_tray(self) -> bool:
        """Tray capture actions stay available while paused (busy still blocks)."""
        if self._exiting or self._busy:
            return False
        return not self._in_transition()

    def _in_transition(self) -> bool:
        return time.monotonic() < self._transition_until

    def _prepare_save_dir(self, path: str) -> str:
        try:
            return config.ensure_save_dir(path)
        except OSError:
            try:
                return config.ensure_save_dir(config.DEFAULTS["save_path"])
            except OSError as exc:
                print(f"CapturMDC: carpeta de guardado no escribible ({exc})", file=sys.stderr)
                return str(config.DEFAULTS["save_path"])

    # ------------------------------------------------------------------- startup
    def start(self) -> None:
        self.tray.start()
        self.tray.refresh()
        self.hotkeys.start()
        self.root.after(POLL_MS, self._poll)

    def run(self) -> None:
        self.start()
        try:
            self.root.mainloop()
        finally:
            self._shutdown()

    def _poll(self) -> None:
        if self._exiting:
            return
        while True:
            try:
                action = self._queue.get_nowait()
            except queue.Empty:
                break
            self._dispatch(action)
        if not self._exiting:
            self.root.after(POLL_MS, self._poll)

    def _dispatch(self, action: str) -> None:
        if self._exiting:
            return
        if action == "quit":
            self._quit()
        elif action == "open_settings":
            self._open_settings()
        elif action == "toggle_pause":
            self._toggle_pause()
        elif action == "capture_full":
            if self._allow_tray():
                self._capture_full()
        elif action == "capture_partial":
            if self._allow_tray():
                self._capture_partial()

    # -------------------------------------------------------------------- capture
    def _capture_full(self) -> None:
        self._busy = True
        try:
            self._emit_image(capture.grab_full_image())
        except Exception as exc:
            self.tray.notify(f"Error de captura: {exc}")
        finally:
            self._busy = False

    def _capture_partial(self) -> None:
        """Freeze the whole screen first, then crop from that frozen snapshot."""
        self._busy = True
        self._selection_active = True
        try:
            snapshot = capture.grab_full_image()
            monitor = capture.get_virtual_monitor()
            image = selection.select_image(self.root, snapshot, monitor)
            if image is None:
                self.tray.notify("Selección cancelada")
            else:
                self._emit_image(image)
        except Exception as exc:
            self.tray.notify(f"Error de selección: {exc}")
        finally:
            self._selection_active = False
            self._busy = False

    def _emit_image(self, image: Any) -> None:
        """Save the image to disk, or copy it to the clipboard when autosave is off."""
        try:
            if bool(self.cfg["autosave"]):
                path = self._save_image(image)
                if path:
                    self.tray.notify(f"Guardado: {path}")
            else:
                capture.copy_image_to_clipboard(image)
                self.tray.notify("Copiado al portapapeles")
        except Exception as exc:
            self.tray.notify(f"Error de captura: {exc}")

    def _save_image(self, image: Any) -> str:
        save_dir = config.ensure_save_dir(self.cfg["save_path"])
        cfg = dict(self.cfg)
        cfg["save_path"] = save_dir
        filename, full_path = config.build_filename(cfg)
        return capture.save_image(
            image,
            save_dir,
            filename,
            str(cfg["output_format"]),
            int(cfg["jpeg_quality"]),
        )

    # --------------------------------------------------------------------- pause
    def _toggle_pause(self) -> None:
        if self._busy or self._in_transition():
            return
        self._paused = not self._paused
        self._blocked_reason = None
        self._transition_until = time.monotonic() + float(self.cfg["pause_resume_transition"])
        self.hotkeys.reset()
        self.tray.refresh()
        self.tray.notify("Capturas en pausa" if self._paused else "Capturas activas")

    # ------------------------------------------------------------------ settings
    def _open_settings(self) -> None:
        if self.settings is not None:
            try:
                self.settings.lift()
                self.settings.focus_force()
            except Exception:  # pragma: no cover - defensive
                pass
            return
        try:
            self.root.update_idletasks()
        except Exception:  # pragma: no cover - defensive
            pass
        window = SettingsWindow(self.root, self.cfg, self._apply_config, self._settings_closed)
        self.settings = window
        self.hotkeys.reset()

    def _settings_closed(self) -> None:
        self.settings = None
        self.hotkeys.reset()

    def _apply_config(self, validated: Dict[str, Any]) -> None:
        config.save_config(validated)
        self.cfg = validated
        self.cfg["save_path"] = self._prepare_save_dir(self.cfg["save_path"])
        ctk.set_appearance_mode(str(self.cfg["theme"]))
        self.hotkeys.set_hotkeys(
            self.cfg["full_hotkey"],
            self.cfg["partial_hotkey"],
            float(self.cfg["partial_delay"]),
            float(self.cfg["max_capture_timeout"]),
        )
        self.tray.refresh()
        self.tray.notify("Configuración guardada")

    # --------------------------------------------------------------------- exit
    def _quit(self) -> None:
        self._exiting = True
        self._shutdown()
        try:
            self.root.quit()
        except Exception:  # pragma: no cover - defensive
            pass

    def _shutdown(self) -> None:
        self._exiting = True
        try:
            self.hotkeys.stop()
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            self.tray.stop()
        except Exception:  # pragma: no cover - defensive
            pass
        if self.settings is not None:
            try:
                self.settings.destroy()
            except Exception:  # pragma: no cover - defensive
                pass
            self.settings = None


def main() -> None:
    app = App()
    app.run()


if __name__ == "__main__":
    main()
