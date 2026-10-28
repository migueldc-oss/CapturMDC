"""Partial selection overlay (plain Tk) over a frozen full-screen snapshot."""

from __future__ import annotations

import time
import tkinter as tk
from typing import Dict, Optional

from PIL import Image, ImageTk

BORDER_COLOR = "#00d0ff"
BACKGROUND_COLOR = "#0b1320"
TINT = 0.28
ALPHA = 0.35
MIN_SELECTION = 6


class SelectionOverlay:
    """Frozen screenshot + dotted drag-selection box.

    The overlay shows a static copy of the screen so animated content cannot
    move while the user drags; the crop is taken from that snapshot, not from a
    second live capture.
    """

    def __init__(self, master: tk.Misc, snapshot: Image.Image, monitor: Optional[Dict[str, int]] = None) -> None:
        self.snapshot = snapshot
        mon = monitor or {}
        self.monitor = {
            "left": int(mon.get("left", 0)),
            "top": int(mon.get("top", 0)),
            "width": int(mon.get("width", snapshot.width)),
            "height": int(mon.get("height", snapshot.height)),
        }
        self.region: Optional[dict[str, int]] = None
        self.image: Optional[Image.Image] = None
        self._origin: Optional[tuple[int, int]] = None
        self._current: Optional[tuple[int, int]] = None
        self._done = False

        self.gate = tk.StringVar(master=master)

        self.window = tk.Toplevel(master)
        self.window.overrideredirect(True)
        self.window.geometry(
            f"{self.monitor['width']}x{self.monitor['height']}+{self.monitor['left']}+{self.monitor['top']}"
        )
        self.window.configure(bg=BACKGROUND_COLOR)
        try:
            # Fully opaque: the frozen snapshot must hide whatever is live below.
            self.window.attributes("-alpha", 1.0)
            self.window.attributes("-topmost", True)
        except tk.TclError:  # pragma: no cover - alpha unsupported on some shells
            pass

        self.canvas = tk.Canvas(self.window, bg=BACKGROUND_COLOR, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.photo = ImageTk.PhotoImage(self._tinted(snapshot))
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.image = self.photo  # keep a reference alive

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.window.bind("<Escape>", self._cancel)
        self.window.bind("<KeyRelease-Escape>", self._cancel)

        self.window.update_idletasks()
        self._hint = self.canvas.create_text(
            max(160, self.canvas.winfo_width() // 2),
            max(90, self.canvas.winfo_height() // 2),
            text="Arrastra para recortar la imagen congelada · Esc para cancelar",
            fill=BORDER_COLOR,
            font=("Segoe UI", 12),
        )

        self.window.focus_force()
        try:
            self.window.grab_set()
        except tk.TclError:  # pragma: no cover - defensive
            pass

    # ------------------------------------------------------------------- helpers
    @staticmethod
    def _tinted(snapshot: Image.Image) -> Image.Image:
        """Blend the snapshot with a dark tint so frozen mode is obvious."""
        tint = Image.new("RGB", snapshot.size, BACKGROUND_COLOR)
        return Image.blend(snapshot.convert("RGB"), tint, TINT)

    def _clamp(self, x: int, y: int) -> tuple[int, int]:
        width = max(1, self.snapshot.width)
        height = max(1, self.snapshot.height)
        return max(0, min(width, x)), max(0, min(height, y))

    def _draw(self) -> None:
        self.canvas.delete("selection")
        if self._origin is None or self._current is None:
            return
        x0, y0 = self._origin
        x1, y1 = self._current
        self.canvas.create_rectangle(
            x0,
            y0,
            x1,
            y1,
            outline=BORDER_COLOR,
            width=2,
            dash=(6, 4),
            tags="selection",
        )
        self.canvas.create_text(
            (x0 + x1) // 2,
            max(0, min(y0, y1) - 12),
            text=f"{abs(x1 - x0)} x {abs(y1 - y0)} px",
            fill=BORDER_COLOR,
            font=("Segoe UI", 11),
            tags="selection",
        )

    # -------------------------------------------------------------------- events
    def _press(self, event: tk.Event) -> None:
        self._origin = self._clamp(event.x, event.y)
        self._current = self._origin
        self._draw()

    def _drag(self, event: tk.Event) -> None:
        if self._origin is None:
            return
        self._current = self._clamp(event.x, event.y)
        self._draw()

    def _release(self, event: tk.Event) -> None:
        if self._origin is None:
            self._cancel()
            return
        self._current = self._clamp(event.x, event.y)
        self._draw()
        x0, x1 = sorted((self._origin[0], self._current[0]))
        y0, y1 = sorted((self._origin[1], self._current[1]))
        width = x1 - x0
        height = y1 - y0
        if width < MIN_SELECTION or height < MIN_SELECTION:
            self._cancel()
            return
        self.region = {"left": x0, "top": y0, "width": width, "height": height}
        self.image = self.snapshot.crop((x0, y0, x1, y1))
        self._finish()

    def _cancel(self, event: Optional[tk.Event] = None) -> None:
        self.region = None
        self.image = None
        self._finish()

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        self.gate.set("done")

    def hide(self) -> None:
        """Take the overlay off screen before writing the result out."""
        try:
            self.window.withdraw()
            self.window.attributes("-alpha", 0.0)
        except tk.TclError:  # pragma: no cover - defensive
            pass
        try:
            self.window.update_idletasks()
        except tk.TclError:  # pragma: no cover - defensive
            pass
        time.sleep(0.10)

    def destroy(self) -> None:
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        try:
            del self.photo
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            self.window.destroy()
        except tk.TclError:  # pragma: no cover - already destroyed
            pass


def select_image(master: tk.Misc, snapshot: Image.Image, monitor: Optional[Dict[str, int]] = None) -> Optional[Image.Image]:
    """Block until the user drags over the frozen snapshot; returns a cropped image.

    ``None`` means the selection was cancelled. Uses ``master.wait_variable`` so
    the hidden root mainloop keeps pumping while the overlay is visible.
    """
    overlay = SelectionOverlay(master, snapshot, monitor)
    try:
        master.wait_variable(overlay.gate)
        image = overlay.image
        overlay.hide()
        return image
    finally:
        overlay.destroy()
