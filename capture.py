"""Windows screen capture: DPI-aware full/region grabs, PNG/JPG saving, CF_DIB clipboard."""

from __future__ import annotations

import ctypes
import os
import struct
import time
from typing import Any, Dict, Optional

import mss
from PIL import Image

import win32clipboard

# Windows clipboard/global-memory constants.
GMEM_MOVEABLE = 0x0002
BI_RGB = 0
_BITMAPINFOHEADER_SIZE = 40

_kernel32 = ctypes.windll.kernel32
_user32 = ctypes.windll.user32

_kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
_kernel32.GlobalAlloc.restype = ctypes.c_void_p
_kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
_kernel32.GlobalUnlock.restype = ctypes.c_int
_kernel32.GlobalFree.argtypes = (ctypes.c_void_p,)
_kernel32.GlobalFree.restype = ctypes.c_void_p
_kernel32.GetLastError.argtypes = ()
_kernel32.GetLastError.restype = ctypes.c_uint
_user32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)
_user32.SetClipboardData.restype = ctypes.c_void_p


def ensure_dpi_aware() -> None:
    """Mark the process DPI-aware so mss reports physical pixel coordinates."""
    try:
        _user32.SetProcessDPIAware()
    except AttributeError:  # pragma: no cover - non-Windows fallback
        pass


def get_virtual_monitor() -> Dict[str, int]:
    """Return the full virtual screen (all monitors) as an mss region dict."""
    ensure_dpi_aware()
    with mss.MSS() as session:
        monitor = session.monitors[0]
        return {
            "left": int(monitor["left"]),
            "top": int(monitor["top"]),
            "width": int(monitor["width"]),
            "height": int(monitor["height"]),
        }


def _grab(region: Dict[str, int]) -> Image.Image:
    ensure_dpi_aware()
    left = int(region["left"])
    top = int(region["top"])
    width = max(1, int(region["width"]))
    height = max(1, int(region["height"]))
    with mss.MSS() as session:
        shot = session.grab({"left": left, "top": top, "width": width, "height": height})
        return Image.frombytes("RGB", shot.size, shot.rgb)


def grab_full_image() -> Image.Image:
    """Capture the whole virtual multi-monitor screen."""
    return _grab(get_virtual_monitor())


def grab_region_image(region: Dict[str, int]) -> Image.Image:
    """Capture an arbitrary virtual-screen region (may use negative offsets)."""
    return _grab(region)


def save_image(
    image: Image.Image,
    save_dir: str,
    filename: str,
    output_format: str = "png",
    jpeg_quality: int = 90,
) -> str:
    """Save the image as PNG or JPG and return the absolute path."""
    os.makedirs(save_dir, exist_ok=True)
    path = os.path.join(save_dir, filename)
    fmt = "JPEG" if output_format.lower() in ("jpg", "jpeg") else "PNG"
    kwargs: Dict[str, Any] = {}
    if fmt == "JPEG":
        kwargs["quality"] = max(1, min(100, int(jpeg_quality)))
        kwargs["optimize"] = True
    image.save(path, fmt, **kwargs)
    return path


def build_dib(image: Image.Image) -> bytes:
    """Build a CF_DIB payload: BITMAPINFOHEADER + bottom-up padded 24bpp rows."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width <= 0 or height <= 0:
        raise ValueError("La imagen capturada está vacía")

    # Windows 24 bpp BI_RGB DIBs store pixels as B,G,R; PIL stores R,G,B, so the
    # channels must be reversed before writing the rows.
    bgr = Image.merge("RGB", tuple(reversed(rgb.split())))

    row_bytes = width * 3
    stride = (row_bytes + 3) & ~3
    padding = stride - row_bytes

    raw = bgr.tobytes()
    rows = bytearray()
    # CF_DIB with a positive biHeight is bottom-up: the first buffer row must be
    # the last (bottom) scanline of the image, so append the source rows reversed.
    for y in range(height - 1, -1, -1):
        row = raw[y * row_bytes:(y + 1) * row_bytes]
        rows += row
        if padding:
            rows += b"\x00" * padding

    pixel_size = stride * height
    header = struct.pack(
        "<IiiHHIIiiII",
        _BITMAPINFOHEADER_SIZE,
        width,
        height,  # positive height => bottom-up DIB
        1,
        24,
        BI_RGB,
        pixel_size,
        0,
        0,
        0,
        0,
    )
    return bytes(header) + bytes(rows)


def _open_clipboard(retries: int = 8, delay: float = 0.05) -> None:
    last_error: Optional[BaseException] = None
    for _ in range(retries):
        try:
            win32clipboard.OpenClipboard()
            return
        except Exception as exc:  # pywin32 raises win32clipboard.error
            last_error = exc
            time.sleep(delay)
    raise RuntimeError("El portapapeles de Windows está ocupado") from last_error


def copy_image_to_clipboard(image: Image.Image) -> int:
    """Copy the image to the Windows clipboard as CF_DIB. Returns payload size."""
    payload = build_dib(image)
    hmem = None
    opened = False
    try:
        _open_clipboard()
        opened = True
        win32clipboard.EmptyClipboard()

        hmem = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(payload))
        if not hmem:
            raise RuntimeError("GlobalAlloc falló para los datos del portapapeles")

        pointer = _kernel32.GlobalLock(hmem)
        if not pointer:
            _kernel32.GlobalFree(hmem)
            hmem = None
            raise RuntimeError("GlobalLock falló para los datos del portapapeles")

        ctypes.memmove(pointer, payload, len(payload))
        # GlobalUnlock can report FALSE without a real error on the heap-backed
        # implementation, so only a non-zero GetLastError() counts as failure.
        if not _kernel32.GlobalUnlock(hmem) and _kernel32.GetLastError():
            _kernel32.GlobalFree(hmem)
            hmem = None
            raise RuntimeError("GlobalUnlock falló para los datos del portapapeles")

        placed = _user32.SetClipboardData(win32clipboard.CF_DIB, hmem)
        if not placed:
            _kernel32.GlobalFree(hmem)
            hmem = None
            raise RuntimeError("SetClipboardData(CF_DIB) falló")

        # Ownership of hmem transfers to the clipboard on success.
        hmem = None
        return len(payload)
    finally:
        if hmem:
            _kernel32.GlobalFree(hmem)
        if opened:
            try:
                win32clipboard.CloseClipboard()
            except Exception:  # pragma: no cover - defensive cleanup
                pass
