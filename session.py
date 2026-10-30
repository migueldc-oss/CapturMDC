"""Windows session notifications so hotkeys can be re-registered after a session change.

A low-level keyboard hook belongs to the window station/desktop of the session
that installed it. After suspend, lock or a fast user switch the hook often
stops delivering events, so the app listens for ``WM_WTSSESSION_CHANGE`` and
re-installs the hook when the user comes back (logon, unlock, console connect).
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable, Optional, Set

# Dedicated WinDLL instances: ctypes.windll.user32 is a shared object, and
# declaring argtypes on it would override pynput's own GetMessageW signature
# and kill the keyboard listener thread.
user32 = ctypes.WinDLL("user32")
kernel32 = ctypes.WinDLL("kernel32")
wtsapi32 = ctypes.WinDLL("wtsapi32")

# Window messages.
WM_QUIT = 0x0012
WM_WTSSESSION_CHANGE = 0x02B1

# WTS session event codes (wParam of WM_WTSSESSION_CHANGE).
WTS_SESSION_CONNECT = 2
WTS_SESSION_DISCONNECT = 3
WTS_SESSION_CONSOLE_CONNECT = 4
WTS_SESSION_LOGON = 5
WTS_SESSION_LOGOFF = 6
WTS_SESSION_LOCK = 7
WTS_SESSION_UNLOCK = 8
WTS_SESSION_REMOTE_CONNECT = 10
WTS_SESSION_REMOTE_DISCONNECT = 11

#: Events that mean the user can press keys again: re-arm the hotkeys.
RESUME_EVENTS: Set[int] = {
    WTS_SESSION_CONNECT,
    WTS_SESSION_CONSOLE_CONNECT,
    WTS_SESSION_LOGON,
    WTS_SESSION_UNLOCK,
    WTS_SESSION_REMOTE_CONNECT,
}

NOTIFY_FOR_THIS_SESSION = 0
NOTIFY_FOR_ALL_SESSIONS = 1

HWND_MESSAGE = ctypes.c_void_p(-3)
ERROR_CLASS_ALREADY_EXISTS = 1412  # ERROR_CLASS_ALREADY_EXISTS

# Python's wintypes has no LRESULT; it is a LONG_PTR.
LRESULT = ctypes.c_ssize_t

_WNDPROC_TYPE = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("style", ctypes.c_uint),
        ("lpfnWndProc", _WNDPROC_TYPE),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", ctypes.c_uint),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", ctypes.c_uint),
        ("pt", wintypes.POINT),
    ]


user32.RegisterClassExW.argtypes = (ctypes.POINTER(WNDCLASSEXW),)
user32.RegisterClassExW.restype = ctypes.c_ushort
user32.CreateWindowExW.argtypes = (
    ctypes.c_uint,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    ctypes.c_uint,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.HINSTANCE,
    ctypes.c_void_p,
)
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = (wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.restype = LRESULT
user32.GetMessageW.argtypes = (ctypes.POINTER(MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint)
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = (ctypes.POINTER(MSG),)
user32.DispatchMessageW.argtypes = (ctypes.POINTER(MSG),)
user32.PostMessageW.argtypes = (wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
user32.PostMessageW.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = (ctypes.c_uint, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = (wintypes.HWND,)
user32.DestroyWindow.restype = wintypes.BOOL
user32.UnregisterClassW.argtypes = (wintypes.LPCWSTR, wintypes.HINSTANCE)
user32.UnregisterClassW.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GetCurrentThreadId.restype = ctypes.c_uint
kernel32.GetLastError.restype = ctypes.c_uint
kernel32.SetLastError.argtypes = (ctypes.c_uint,)
wtsapi32.WTSRegisterSessionNotification.argtypes = (wintypes.HWND, ctypes.c_uint)
wtsapi32.WTSRegisterSessionNotification.restype = wintypes.BOOL
wtsapi32.WTSUnRegisterSessionNotification.argtypes = (wintypes.HWND,)
wtsapi32.WTSUnRegisterSessionNotification.restype = wintypes.BOOL


class SessionWatcher:
    """Hidden message-only window that reports ``WM_WTSSESSION_CHANGE`` events."""

    def __init__(
        self,
        on_event: Callable[[int], None],
        notify_all_sessions: bool = True,
        class_name: Optional[str] = None,
    ) -> None:
        self._on_event = on_event
        self._notify_all = NOTIFY_FOR_ALL_SESSIONS if notify_all_sessions else NOTIFY_FOR_THIS_SESSION
        # Unique per instance so start/stop cycles never reuse a stale wndproc.
        self._class_name = class_name or f"CapturMDCSessionWatcher-{id(self):x}"
        self._hinstance = kernel32.GetModuleHandleW(None)
        self._class_registered = False
        self._wndproc: Optional[_WNDPROC_TYPE] = None
        self._hwnd: Optional[int] = None
        self._thread_id: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._registered = False

    # ---------------------------------------------------------------- callbacks
    def _window_proc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == WM_WTSSESSION_CHANGE:
            try:
                self._on_event(int(wparam))
            except Exception:  # pragma: no cover - the watcher must never crash
                pass
            return 0
        return int(user32.DefWindowProcW(hwnd, msg, wparam, lparam))

    # ------------------------------------------------------------------ startup
    def start(self, timeout: float = 3.0) -> bool:
        """Start the watcher thread and wait until its window exists."""
        if self._thread is not None and self._thread.is_alive():
            return self._hwnd is not None
        self._stop.clear()
        self._ready.clear()
        thread = threading.Thread(target=self._run, name="CapturMDC-session-watch", daemon=True)
        self._thread = thread
        thread.start()
        self._ready.wait(timeout)
        return self._hwnd is not None

    def _create_window(self) -> Optional[int]:
        self._wndproc = _WNDPROC_TYPE(self._window_proc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = self._hinstance
        wc.lpszClassName = self._class_name
        kernel32.SetLastError(0)
        atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not atom:
            if kernel32.GetLastError() != ERROR_CLASS_ALREADY_EXISTS:
                return None
        else:
            self._class_registered = True

        hwnd = user32.CreateWindowExW(
            0,
            self._class_name,
            None,
            0,
            0,
            0,
            0,
            0,
            HWND_MESSAGE,
            None,
            self._hinstance,
            None,
        )
        if not hwnd:
            return None
        self._hwnd = hwnd
        self._registered = bool(wtsapi32.WTSRegisterSessionNotification(hwnd, self._notify_all))
        return hwnd

    def _run(self) -> None:
        try:
            self._thread_id = kernel32.GetCurrentThreadId()
            if not self._create_window():
                return
            self._ready.set()

            msg = MSG()
            while not self._stop.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:  # WM_QUIT or error: end the loop
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._teardown()

    def _teardown(self) -> None:
        hwnd = self._hwnd
        if hwnd:
            if self._registered:
                try:
                    wtsapi32.WTSUnRegisterSessionNotification(hwnd)
                except Exception:  # pragma: no cover - defensive
                    pass
                self._registered = False
            try:
                user32.DestroyWindow(hwnd)
            except Exception:  # pragma: no cover - defensive
                pass
        self._hwnd = None
        if self._class_registered:
            try:
                user32.UnregisterClassW(self._class_name, self._hinstance)
            except Exception:  # pragma: no cover - defensive
                pass
            self._class_registered = False

    # ------------------------------------------------------------------- shutdown
    def stop(self, timeout: float = 3.0) -> None:
        """Post ``WM_QUIT`` to the watcher thread and wait for it to finish."""
        self._stop.set()
        thread_id = self._thread_id
        if thread_id:
            try:
                user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            except Exception:  # pragma: no cover - defensive
                pass
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout)
        self._thread_id = None

    @property
    def active(self) -> bool:
        return self._hwnd is not None and self._thread is not None and self._thread.is_alive()

    @property
    def notifications_enabled(self) -> bool:
        return bool(self._registered)

    def wait(self, timeout: float = 1.0) -> bool:
        self._ready.wait(timeout)
        return self._hwnd is not None

    def simulate_event(self, event: int) -> bool:
        """Post a session-change message to our own window (used for tests)."""
        hwnd = self._hwnd
        if not hwnd:
            return False
        return bool(user32.PostMessageW(hwnd, WM_WTSSESSION_CHANGE, event, 0))
