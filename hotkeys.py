"""Hotkey normalization, validation and exact held-key matching for CapturMDC.

Important: this module must never import ``config``; ``config`` imports this
module, so a reverse import would create a circular dependency.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from typing import Callable, Dict, Iterable, List, Optional, Sequence

try:  # pynput is required at runtime, but keep import errors diagnosable.
    from pynput.keyboard import Key
except Exception:  # pragma: no cover - defensive
    Key = None

# Canonical display order: modifiers first (Ctrl, Alt, Shift), base key last.
MODIFIER_ORDER: Sequence[str] = ("ctrl", "alt", "shift")
MODIFIER_TOKENS: frozenset = frozenset(MODIFIER_ORDER)

MODIFIER_ALIASES: Dict[str, str] = {
    "ctrl": "ctrl",
    "ctl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
}

PRINT_SCREEN_ALIASES: Dict[str, str] = {
    "prsc": "prsc",
    "printscreen": "prsc",
    "print_screen": "prsc",
    "print screen": "prsc",
}

DISPLAY_NAMES: Dict[str, str] = {
    "ctrl": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "prsc": "PrSc",
}

# pynput key names -> canonical tokens.
PYNPUT_NAME_TOKENS: Dict[str, str] = {
    "ctrl": "ctrl",
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "alt": "alt",
    "alt_l": "alt",
    "alt_r": "alt",
    "altgr": "alt",
    "alt_gr": "alt",
    "shift": "shift",
    "shift_l": "shift",
    "shift_r": "shift",
    "print_screen": "prsc",
    "prsc": "prsc",
}

# Virtual key codes for A-Z. Windows reports control characters (e.g. Ctrl+M ->
# '\r') instead of the letter once Ctrl is held, so VK codes are the reliable
# way to recognise letter hotkeys combined with modifiers.
VK_LETTER_TOKENS: Dict[int, str] = {vk: chr(vk).lower() for vk in range(0x41, 0x5B)}

ActionCallback = Callable[[str], None]


def _is_letter(token: str) -> bool:
    return len(token) == 1 and "a" <= token <= "z"


def tokens_to_display(tokens: Iterable[str]) -> str:
    """Render canonical tokens in canonical display order."""
    mods = [t for t in MODIFIER_ORDER if t in tokens]
    base = [t for t in tokens if t not in MODIFIER_TOKENS]
    parts = mods + base
    return "+".join(DISPLAY_NAMES.get(t, t.upper()) for t in parts)


def canonical_tokens(raw: object) -> List[str]:
    """Normalize a hotkey string to lowercase canonical tokens.

    Raises ``ValueError`` for empty values, duplicate modifiers, modifier-only
    combinations, unsupported keys and bare letters.
    """
    if not isinstance(raw, str):
        raise ValueError("La combinación de teclas debe ser texto")

    text = raw.strip()
    if not text:
        raise ValueError("La combinación de teclas está vacía")

    parts = [p.strip().lower() for p in text.split("+")]
    if any(not p for p in parts):
        raise ValueError("La combinación de teclas tiene partes vacías")

    tokens: List[str] = []
    for part in parts:
        if part in MODIFIER_ALIASES:
            tokens.append(MODIFIER_ALIASES[part])
        elif part in PRINT_SCREEN_ALIASES:
            tokens.append(PRINT_SCREEN_ALIASES[part])
        elif _is_letter(part):
            tokens.append(part)
        else:
            raise ValueError(f"Tecla no admitida: {part!r}")

    base = tokens[-1]
    modifiers = tokens[:-1]

    for token in modifiers:
        if token not in MODIFIER_TOKENS:
            raise ValueError("La tecla base debe ser la última")

    if base in MODIFIER_TOKENS:
        raise ValueError("La combinación solo contiene modificadores")

    duplicates = [t for t, n in Counter(modifiers).items() if n > 1]
    if duplicates:
        raise ValueError(f"Modificador duplicado: {DISPLAY_NAMES[duplicates[0]]}")

    if _is_letter(base) and not modifiers:
        raise ValueError("Una letra requiere Ctrl, Alt o Shift")

    ordered = [t for t in MODIFIER_ORDER if t in modifiers] + [base]
    return ordered


def normalize_hotkey(raw: object) -> str:
    """Return the canonical display form (e.g. ``Ctrl+Shift+PrSc``)."""
    return tokens_to_display(canonical_tokens(raw))


def is_valid_hotkey(raw: object) -> bool:
    try:
        normalize_hotkey(raw)
    except ValueError:
        return False
    return True


def matches_exact(tokens: Sequence[str], held: Counter, unsupported: int) -> bool:
    """Exact held-key matching: same counts per token and no unsupported keys."""
    if unsupported:
        return False
    if Counter(tokens) != Counter(held):
        return False
    return True


def key_token(key: object) -> Optional[str]:
    """Map a pynput key object to a canonical token, or ``None`` if unsupported."""
    name = getattr(key, "name", None)
    if isinstance(name, str):
        token = PYNPUT_NAME_TOKENS.get(name.lower())
        if token:
            return token

    vk = getattr(key, "vk", None)
    if isinstance(vk, int):
        token = VK_LETTER_TOKENS.get(vk)
        if token:
            return token

    char = getattr(key, "char", None)
    if isinstance(char, str) and len(char) == 1:
        lowered = char.lower()
        if _is_letter(lowered):
            return lowered

    return None


def key_identity(key: object) -> str:
    """Stable identity for a held key (deduplicates auto-repeat events)."""
    token = key_token(key)
    if token:
        # Modifiers and PrSc are grouped by token: ctrl_l and ctrl_r count once.
        return token
    name = getattr(key, "name", None)
    vk = getattr(key, "vk", None)
    char = getattr(key, "char", None)
    if isinstance(name, str):
        return f"unsupported:{name}"
    if isinstance(vk, int):
        return f"unsupported:vk{vk}"
    if isinstance(char, str):
        return f"unsupported:{char!r}"
    return f"unsupported:{key!r}"


class HotkeyController:
    """Exact held-key hotkey controller driven by ``pynput.keyboard.Listener``.

    The full hotkey fires immediately and is checked before the partial hotkey.
    The partial hotkey fires after ``partial_delay`` and is cancelled when the
    full hotkey becomes an exact match, an unsupported key is held, the allow
    predicate turns false, or the capture timeout elapses. Releasing the keys
    does not cancel it, so a quick tap of the partial combination still fires.
    """

    def __init__(
        self,
        full_hotkey: Optional[str] = "Ctrl+PrSc",
        partial_hotkey: Optional[str] = "PrSc",
        callback: Optional[ActionCallback] = None,
        allow_action: Optional[Callable[[], bool]] = None,
        partial_delay: float = 0.25,
        max_capture_timeout: float = 30.0,
    ) -> None:
        self._callback = callback
        self._allow = allow_action or (lambda: True)
        self._lock = threading.Lock()

        self._partial_delay = 0.25
        self._max_timeout = 30.0
        self._held: Dict[str, str] = {}
        self._unsupported: Dict[str, str] = {}
        self._full_fired = False
        self._partial_fired = False
        self._partial_timer: Optional[threading.Timer] = None
        self._partial_deadline: Optional[float] = None

        self._full_tokens: List[str] = []
        self._partial_tokens: List[str] = []
        self.set_hotkeys(full_hotkey, partial_hotkey, partial_delay, max_capture_timeout)

        self._listener = None
        self._started = False

    # ------------------------------------------------------------------ config
    def set_hotkeys(
        self,
        full_hotkey: Optional[str],
        partial_hotkey: Optional[str],
        partial_delay: Optional[float] = None,
        max_capture_timeout: Optional[float] = None,
    ) -> None:
        self._full_tokens = canonical_tokens(full_hotkey) if full_hotkey else []
        self._partial_tokens = canonical_tokens(partial_hotkey) if partial_hotkey else []
        if partial_delay is not None:
            self._partial_delay = max(0.0, float(partial_delay))
        if max_capture_timeout is not None:
            self._max_timeout = max(1.0, float(max_capture_timeout))
        self.reset()

    def reset(self) -> None:
        """Clear fired/timer state; used when busy or pause state changes."""
        self._cancel_partial_timer()
        with self._lock:
            self._held.clear()
            self._unsupported.clear()
            self._full_fired = False
            self._partial_fired = False
            self._partial_deadline = None

    # ------------------------------------------------------------------- state
    def _counts_locked(self) -> tuple[Counter, int]:
        counts = Counter(self._held.values())
        return counts, len(self._unsupported)

    def _matches_locked(self, tokens: Sequence[str], counts: Counter, unsupported: int) -> bool:
        if unsupported:
            return False
        if Counter(tokens) != counts:
            return False
        return True

    # ------------------------------------------------------------------- timers
    def _cancel_partial_timer(self) -> None:
        timer = self._partial_timer
        self._partial_timer = None
        if timer is not None:
            timer.cancel()

    def _schedule_partial_locked(self) -> None:
        if self._partial_timer is not None or self._partial_fired or self._full_fired:
            return
        now = time.monotonic()
        if self._partial_deadline is None:
            self._partial_deadline = now + self._max_timeout
        remaining = self._partial_deadline - now
        delay = min(self._partial_delay, remaining)
        if delay <= 0.0:
            self._partial_deadline = None
            return
        timer = threading.Timer(delay, self._check_partial)
        timer.daemon = True
        self._partial_timer = timer
        timer.start()

    def _check_partial(self) -> None:
        with self._lock:
            self._partial_timer = None
            if self._partial_deadline is None:
                return
            now = time.monotonic()
            if now > self._partial_deadline:
                self._partial_deadline = None
                return
            if self._full_fired:
                self._partial_deadline = None
                return
            if not self._allow():
                self._partial_deadline = None
                return
            counts, unsupported = self._counts_locked()
            if self._full_tokens and self._matches_locked(self._full_tokens, counts, unsupported):
                # The full combination became exact while waiting.
                self._partial_deadline = None
                return
            if not self._partial_tokens:
                return
            # The partial combination was exact when the timer was scheduled;
            # keys may already be released, so a quick tap still fires.
            self._partial_fired = True
            self._partial_deadline = None
        self._fire("capture_partial")

    def _fire(self, action: str) -> None:
        callback = self._callback
        if callback is None:
            return
        try:
            callback(action)
        except Exception:  # pragma: no cover - listener must never crash
            pass

    # ---------------------------------------------------------------- listener
    def _on_press(self, key: object) -> None:
        token = key_token(key)
        with self._lock:
            if token is None:
                self._unsupported[key_identity(key)] = "unsupported"
            else:
                self._held[token] = token
            counts, unsupported = self._counts_locked()

        if not self._allow():
            self._cancel_partial_timer()
            return

        if self._full_tokens and self._matches_locked(self._full_tokens, counts, unsupported):
            self._cancel_partial_timer()
            if not self._full_fired:
                self._full_fired = True
                self._fire("capture_full")
            return

        if self._partial_tokens and self._matches_locked(self._partial_tokens, counts, unsupported):
            with self._lock:
                self._schedule_partial_locked()
        else:
            self._cancel_partial_timer()

    def _on_release(self, key: object) -> None:
        token = key_token(key)
        with self._lock:
            if token is None:
                self._unsupported.pop(key_identity(key), None)
            else:
                self._held.pop(token, None)
            counts, unsupported = self._counts_locked()
            full_now_exact = bool(self._full_tokens) and self._matches_locked(
                self._full_tokens, counts, unsupported
            )
            idle = not self._held and not self._unsupported

        # Releasing must not cancel a pending partial capture: users tap the
        # combination faster than partial_delay. Only a newly exact full
        # combination cancels it.
        if full_now_exact:
            self._cancel_partial_timer()

        if idle:
            with self._lock:
                self._full_fired = False
                if self._partial_timer is None:
                    self._partial_fired = False
                    self._partial_deadline = None

    def start(self) -> None:
        if self._started or Key is None:
            return
        from pynput.keyboard import Listener

        self._listener = Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        self._started = True

    def stop(self) -> None:
        self._cancel_partial_timer()
        listener = self._listener
        self._listener = None
        self._started = False
        if listener is not None:
            try:
                listener.stop()
            except Exception:  # pragma: no cover - defensive
                pass

    def __enter__(self) -> "HotkeyController":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
