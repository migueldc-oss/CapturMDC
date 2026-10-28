"""JSON configuration for CapturMDC: defaults, load/save, validation, paths."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from typing import Any, Dict, Optional, Tuple

from hotkeys import is_valid_hotkey, normalize_hotkey

APP_NAME = "CapturMDC"

DEFAULT_SAVE_PATH = os.path.join(
    os.path.expandvars("%USERPROFILE%"), "Pictures", APP_NAME
)

DEFAULTS: Dict[str, Any] = {
    "save_path": DEFAULT_SAVE_PATH,
    "filename_pattern": "Screenshot_{timestamp}",
    "timestamp_format": "%Y%m%d_%H%M%S",
    "output_format": "png",
    "jpeg_quality": 90,
    "autosave": True,
    "theme": "dark",
    "full_hotkey": "Ctrl+PrSc",
    "partial_hotkey": "PrSc",
    "partial_delay": 0.25,
    "max_capture_timeout": 30.0,
    "pause_resume_transition": 0.35,
}

_INVALID_FILENAME_CHARS = set('<>:"/\\|?*')
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_TIMESTAMP_PLACEHOLDER = "{timestamp}"
_MAX_FILENAME_CHARS = 200


def config_path() -> str:
    base = os.path.expandvars("%APPDATA%") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME, "config.json")


def _strip_invalid(text: str) -> str:
    cleaned = []
    for ch in text:
        if ch in _INVALID_FILENAME_CHARS or ord(ch) < 32 or ord(ch) == 127:
            continue
        cleaned.append(ch)
    return re.sub(r"\s+", " ", "".join(cleaned)).strip()


def sanitize_filename(pattern: object) -> str:
    """Strip invalid Windows filename characters and control characters.

    ``{timestamp}`` is preserved because braces/underscore are legal characters.
    """
    text = "" if pattern is None else str(pattern)
    name = _strip_invalid(text)
    if not name:
        name = DEFAULTS["filename_pattern"]
    if _TIMESTAMP_PLACEHOLDER not in name:
        name = DEFAULTS["filename_pattern"]
    return name[:_MAX_FILENAME_CHARS]


def extension_for(output_format: str) -> str:
    return ".jpg" if normalize_output_format(output_format) == "jpg" else ".png"


def normalize_output_format(value: object) -> str:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("png", "jpg", "jpeg"):
            return "jpg" if lowered == "jpeg" else lowered
    raise ValueError("Formato de salida inválido (usa png o jpg)")


def normalize_theme(value: object) -> str:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("dark", "light"):
            return lowered
    raise ValueError("Tema inválido (usa dark o light)")


def validate_bool(value: object, name: str, strict: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0"):
        return value.strip().lower() in ("true", "1")
    if strict:
        raise ValueError(f"Valor booleano inválido: {name}")
    return bool(DEFAULTS[name])


def validate_number(value: object, name: str, low: float, high: float, strict: bool) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        if strict:
            raise ValueError(f"Valor numérico inválido: {name}")
        return float(DEFAULTS[name])
    if number < low or number > high:
        if strict:
            raise ValueError(f"{name} debe estar entre {low} y {high}")
        return float(DEFAULTS[name])
    return number


def validate_save_path(value: object, strict: bool) -> str:
    """Expand and normalize the save directory; strict mode raises ValueError."""
    if not isinstance(value, str) or not value.strip():
        if strict:
            raise ValueError("La carpeta de guardado está vacía")
        return str(DEFAULTS["save_path"])

    path = os.path.expandvars(value)
    path = os.path.expanduser(path)
    path = os.path.normpath(path)

    if not os.path.isabs(path):
        path = os.path.abspath(path)

    if os.path.exists(path) and not os.path.isdir(path):
        if strict:
            raise ValueError("La ruta de guardado existe como archivo, no como carpeta")
        return str(DEFAULTS["save_path"])

    return path


def ensure_save_dir(path: str) -> str:
    """Create the save directory and verify it is writable."""
    path = validate_save_path(path, strict=False)
    os.makedirs(path, exist_ok=True)
    probe = os.path.join(path, "capturmdc_probe.tmp")
    try:
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
    except OSError as exc:
        raise OSError(f"La carpeta de guardado no es escribible: {path}") from exc
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass
    return path


def validate_timestamp_format(value: object, strict: bool) -> str:
    if not isinstance(value, str) or not value.strip():
        if strict:
            raise ValueError("El formato de fecha está vacío")
        return str(DEFAULTS["timestamp_format"])
    fmt = value.strip()
    try:
        rendered = time.strftime(fmt, time.localtime())
    except (ValueError, TypeError):
        if strict:
            raise ValueError(f"Formato de fecha inválido: {fmt}")
        return str(DEFAULTS["timestamp_format"])
    if not rendered or any(ch in _INVALID_FILENAME_CHARS or ord(ch) < 32 for ch in rendered):
        if strict:
            raise ValueError("El formato de fecha produce caracteres no válidos en el nombre")
        return str(DEFAULTS["timestamp_format"])
    return fmt


def validate_hotkey(value: object, strict: bool, default: str = DEFAULTS["full_hotkey"]) -> str:
    return _hotkey_value(value, default, strict)


def validate_config(raw: Optional[Dict[str, Any]], strict: bool = False) -> Dict[str, Any]:
    """Build a config dict from ``raw``; invalid values fall back to defaults."""
    source = raw if isinstance(raw, dict) else {}
    cfg: Dict[str, Any] = {}

    cfg["save_path"] = validate_save_path(source.get("save_path", DEFAULTS["save_path"]), strict)
    cfg["output_format"] = _coerce(
        normalize_output_format, source.get("output_format", DEFAULTS["output_format"]), DEFAULTS["output_format"], strict
    )
    cfg["jpeg_quality"] = int(
        validate_number(source.get("jpeg_quality", DEFAULTS["jpeg_quality"]), "jpeg_quality", 1, 100, strict)
    )
    cfg["autosave"] = validate_bool(source.get("autosave", DEFAULTS["autosave"]), "autosave", strict)
    cfg["theme"] = _coerce(normalize_theme, source.get("theme", DEFAULTS["theme"]), DEFAULTS["theme"], strict)
    cfg["filename_pattern"] = _filename_value(source.get("filename_pattern", DEFAULTS["filename_pattern"]), strict)
    cfg["timestamp_format"] = validate_timestamp_format(source.get("timestamp_format", DEFAULTS["timestamp_format"]), strict)
    cfg["full_hotkey"] = _hotkey_value(source.get("full_hotkey", DEFAULTS["full_hotkey"]), DEFAULTS["full_hotkey"], strict)
    cfg["partial_hotkey"] = _hotkey_value(source.get("partial_hotkey", DEFAULTS["partial_hotkey"]), DEFAULTS["partial_hotkey"], strict)
    cfg["partial_delay"] = round(
        validate_number(source.get("partial_delay", DEFAULTS["partial_delay"]), "partial_delay", 0.0, 5.0, strict), 3
    )
    cfg["max_capture_timeout"] = validate_number(
        source.get("max_capture_timeout", DEFAULTS["max_capture_timeout"]), "max_capture_timeout", 1.0, 300.0, strict
    )
    cfg["pause_resume_transition"] = round(
        validate_number(
            source.get("pause_resume_transition", DEFAULTS["pause_resume_transition"]),
            "pause_resume_transition",
            0.0,
            5.0,
            strict,
        ),
        3,
    )
    return cfg


def _coerce(func, value, default, strict: bool):
    """Apply a normalizer; strict re-raises, non-strict falls back to ``default``."""
    try:
        return func(value)
    except (ValueError, TypeError):
        if strict:
            raise
        return default


def _filename_value(value, strict: bool) -> str:
    if strict:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("El patrón de nombre está vacío")
        cleaned = _strip_invalid(value)
        if _TIMESTAMP_PLACEHOLDER not in cleaned:
            raise ValueError("El patrón de nombre debe contener {timestamp}")
        cleaned = cleaned[:_MAX_FILENAME_CHARS]
        if cleaned.upper() in _RESERVED_NAMES:
            raise ValueError("El patrón de nombre usa un nombre reservado de Windows")
        return cleaned
    return sanitize_filename(value)


def _hotkey_value(value, default: str, strict: bool) -> str:
    if is_valid_hotkey(value):
        return normalize_hotkey(value)
    if strict:
        raise ValueError(f"Atajo de teclado inválido: {value!r}")
    return str(default)


def build_filename(cfg: Dict[str, Any], when: Optional[float] = None) -> Tuple[str, str]:
    """Return (filename_with_extension, full_path) for the given config."""
    timestamp = time.strftime(cfg["timestamp_format"], time.localtime(when if when is not None else time.time()))
    timestamp = "".join(ch for ch in timestamp if ch not in _INVALID_FILENAME_CHARS and ord(ch) >= 32)
    pattern = sanitize_filename(cfg["filename_pattern"])
    stem = pattern.replace(_TIMESTAMP_PLACEHOLDER, timestamp)
    stem = stem[:_MAX_FILENAME_CHARS]
    if not stem or stem.upper() in _RESERVED_NAMES:
        stem = DEFAULTS["filename_pattern"].replace(_TIMESTAMP_PLACEHOLDER, timestamp)
    ext = extension_for(cfg["output_format"])
    filename = stem + ext
    return filename, os.path.join(cfg["save_path"], filename)


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load config from JSON, merging onto defaults for missing/invalid values."""
    target = path or config_path()
    raw: Dict[str, Any] = {}
    try:
        with open(target, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            raw = loaded
    except FileNotFoundError:
        raw = {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        raw = {}
    return validate_config(raw, strict=False)


def save_config(cfg: Dict[str, Any], path: Optional[str] = None) -> str:
    """Atomically write validated config JSON; returns the written path."""
    target = path or config_path()
    validated = validate_config(cfg, strict=True)
    directory = os.path.dirname(target) or os.getcwd()
    os.makedirs(directory, exist_ok=True)

    payload = json.dumps(validated, indent=2, ensure_ascii=False)
    try:
        fd, tmp = tempfile.mkstemp(prefix="capturmdc-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        except OSError:
            # Atomic replacement unsupported/failed: write directly as fallback.
            try:
                os.remove(tmp)
            except OSError:
                pass
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(payload)
    except OSError:
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(payload)
    return target
