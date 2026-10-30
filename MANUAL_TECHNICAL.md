# Technical / functional manual — CapturMDC

A Windows tray application with no visible main window, global keyboard hotkeys, full-screen or partial capture (over a frozen snapshot), output copied to the clipboard as `CF_DIB` always, plus a PNG/JPG file when autosave is enabled.

---

## 1. Components and dependencies

| Module | Responsibility | Depends on |
| --- | --- | --- |
| `__main__.py` | Entry point: hidden Tk root, action queue, state flags, orchestration of capture/pause/settings | `capture`, `config`, `hotkeys`, `selection`, `tray`, `settings`, `customtkinter` |
| `config.py` | Defaults, load/save of `%APPDATA%\CapturMDC\config.json`, strict or lenient validation, filename sanitization | `hotkeys` |
| `hotkeys.py` | Hotkey normalization/validation, exact held-key controller, keepalive watchdog | `pynput`, `threading` |
| `session.py` | Windows session notifications (`WM_WTSSESSION_CHANGE`) so hooks can be re-registered | `ctypes` (user32, kernel32, wtsapi32) |
| `capture.py` | DPI-aware `mss` grabs, PNG/JPG saving, `CF_DIB` construction, clipboard copy | `mss`, `PIL`, `win32clipboard`, `ctypes` |
| `selection.py` | Tk selection overlay drawn over the frozen snapshot; returns a cropped image | `tkinter`, `PIL`, `PIL.ImageTk` |
| `settings.py` | CTk settings window with validation and dynamic visibility | `customtkinter`, `tkinter`, `config` |
| `tray.py` | `pystray` tray icon, Spanish menu, state refresh, notifications | `pystray`, `PIL` |
| `make_icon.py` | Generates the multi-size `app.ico` used by the executable | `PIL` |
| `build_exe.cmd` | Rebuilds the executable with PyInstaller | `pyinstaller` |

**Import rule:** `config.py` imports `hotkeys.py`; `hotkeys.py` **never** imports `config.py` (avoids a circular dependency).

Runtime dependencies (`requirements.txt`):

```
customtkinter==6.0.0
mss==10.2.0
pillow==12.3.0
pystray==0.19.5
pywin32==312
pynput==1.8.2
```

Build dependency (`requirements-build.txt`): `pyinstaller==6.22.2`.

---

## 2. Execution and concurrency model

```
Main thread (Tk/CTk mainloop)
  └─ root.after(POLL_MS=120 ms) -> _poll() -> _queue.get_nowait() -> _dispatch(action)

pynput.keyboard.Listener thread (daemon)
  └─ _on_press / _on_release -> callback(action) -> App._post_action -> _queue.put(action)

threading.Timer threads (daemon)
  └─ _check_partial() -> decides whether the partial capture fires

pystray.Icon.run thread (daemon)
  └─ menu events -> App._post_action

HotkeyController watchdog thread (daemon)
  └─ every WATCHDOG_INTERVAL -> reattach() -> re-install the hook if needed

SessionWatcher thread (daemon)
  └─ message-only window + GetMessageW loop -> WM_WTSSESSION_CHANGE -> App._on_session_change
```

- Every action (hotkey or menu) goes through a `queue.Queue[str]` and is processed **only** on the Tk mainloop thread. pynput/pystray callbacks never touch Tk directly.
- The partial selection uses `master.wait_variable(gate)`, which keeps pumping the mainloop while the overlay is open (it does not block the rest of the app).
- Actions: `capture_full`, `capture_partial`, `open_settings`, `toggle_pause`, `quit`.

### State flags

| Flag | Effect |
| --- | --- |
| `_exiting` | Blocks enqueuing and dispatching actions |
| `_busy` | Capture/save in progress; blocks hotkeys **and** menu |
| `_paused` | Blocks only hotkeys; the menu still works |
| `_selection_active` | Blocks hotkeys while the overlay is open |
| `_transition_until` | Short block after `Pausar/Reanudar` (`pause_resume_transition`) |
| `settings is not None` | Blocks hotkeys while the settings window is open |
| `_blocked_reason` / `_blocked_notify` | Anti-spam notification (same reason at most every 2.5 s) |

Predicates:

- `HotkeyController.allow_action = App._allow_hotkey` → blocked when `_exiting`, `_busy`, `_paused`, settings open, selection active, or in transition.
- `App._allow_tray` → blocked when `_exiting`, `_busy`, or in transition (pause does **not** block the menu).

`HotkeyController.reset()` is called on pause/resume, when opening and closing settings, and after changing hotkeys: it clears held keys, timers and the `*_fired` flags so no stale trigger can fire.

---

## 3. Configuration (`config.py`)

### Path

```python
def config_path() -> str:
    base = os.path.expandvars("%APPDATA%") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME, "config.json")   # %APPDATA%\CapturMDC\config.json
```

### Schema and validation

| Key | Type | Range / rule | Default |
| --- | --- | --- | --- |
| `save_path` | str | Directory created and **writable** (probe with `tempfile`) | `%USERPROFILE%\Pictures\CapturMDC` |
| `output_format` | str | `png` / `jpg` (alias `jpeg`) | `png` |
| `jpeg_quality` | int | 1–100 | 90 |
| `autosave` | bool | `true/false` or `"true"/"false"` | `true` |
| `theme` | str | `dark` / `light` | `dark` |
| `filename_pattern` | str | Must contain `{timestamp}`; `<>:"/\|?*` and control chars stripped; max 200 chars; reserved Windows names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`) not used | `Screenshot_{timestamp}` |
| `timestamp_format` | str | Valid strftime that produces text (probed with `time.strftime`) | `%Y%m%d_%H%M%S` |
| `full_hotkey` | str | Hotkey grammar (§4) | `Ctrl+PrSc` |
| `partial_hotkey` | str | Hotkey grammar (§4) | `PrSc` |
| `partial_delay` | float | 0.0–5.0, rounded to 3 decimals | 0.25 |
| `max_capture_timeout` | float | 1.0–300.0 | 30.0 |
| `pause_resume_transition` | float | 0.0–5.0, rounded to 3 decimals | 0.35 |

- `validate_config(raw, strict=False)`: invalid value → replaced by the default (lenient load).
- `validate_config(raw, strict=True)`: raises `ValueError` with a Spanish message → the settings window shows the error and **does not** close.
- `save_config` writes atomically: temporary file in the same directory + `os.replace()`; if `os.replace` fails, manual copy + `os.remove`.
- `build_filename(cfg)` substitutes `{timestamp}` with `time.strftime`, sanitizes the result and returns `(name, absolute_path)`.
- `ensure_save_dir(path)` creates the directory (`makedirs(exist_ok=True)`) and raises `OSError` if it is not writable; `App._prepare_save_dir` falls back to the default and reports it via stderr/notification.

---

## 4. Hotkeys: grammar and matching (`hotkeys.py`)

### Normalization

- Modifier aliases: `ctrl|ctl|control → ctrl`, `alt → alt`, `shift → shift`.
- Base aliases: `prsc|printscreen|print_screen|print screen → prsc`; letters `A-Z → a-z`.
- Canonical display order: modifiers in the order `Ctrl, Alt, Shift`, base last (`tokens_to_display`).
- `canonical_tokens()` rejects: non-string, empty, duplicated modifiers, modifier-only combinations, unsupported keys, letters without a modifier.

### Controller

State per press: `_held: dict[event -> token]`, `_unsupported: dict[event -> repr]`.

- `_matches_locked(tokens, counts, unsupported)`: **exact** multiset match; if any unsupported key is held, the match is invalidated (so `Ctrl+Alt+M+F` triggers nothing).
- Letters are recognised by **VK** (`VK_LETTER_TOKENS`, `0x41–0x5A`) because with `Ctrl` held Windows delivers control characters (e.g. `Ctrl+M` → `\r`) instead of the letter.
- `AltGR` and `_l/_r` variants collapse to `ctrl/alt/shift`.

### Firing sequence

1. `_on_press`: if the **full** hotkey is exact → `_full_fired=True`, immediate `capture_full` callback.
2. If the **partial** hotkey is exact and there is no timer and no `_full_fired` → `_schedule_partial_locked()`:
   - `_partial_deadline = now + max_capture_timeout` (first time),
   - `delay = min(partial_delay, deadline - now)`; if `delay <= 0` it is abandoned.
3. `_check_partial()` (Timer thread) fires `capture_partial` only if: the timer is still pending, the deadline was not exceeded, `_full_fired` is false, `allow_action()` is true, and the full hotkey is **not** exact at that moment.
4. `_on_release`: cancels the partial **only** if the full combination becomes exact. Releasing keys does not cancel the partial → a quick *tap* still produces the partial capture.
5. The partial is also cancelled if an unsupported key appears, if `allow_action()` turns false, or when the deadline expires.

Practical consequence: with partial `Ctrl+Alt+M` and full `Ctrl+Alt+Shift+M`, pressing the first two fires full if `Shift` is added before the delay elapses; otherwise it fires partial. That is why `partial_delay` is configurable.

### Recovery after suspend, lock or user switch

A `WH_KEYBOARD_LL` hook is bound to the desktop/window station of the session that installed it, so it stops delivering events after suspend, the lock screen or a fast user switch. Two mechanisms fix this:

**Session notifications (`session.py`)**

- `SessionWatcher` registers a window class (`RegisterClassExW`), creates a message-only window (`CreateWindowExW` with parent `HWND_MESSAGE`) in a daemon thread, and calls `WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_ALL_SESSIONS)` (`wtsapi32`).
- It uses **private `ctypes.WinDLL("user32"/"kernel32"/"wtsapi32")` instances**. Declaring `argtypes` on the shared `ctypes.windll.user32.GetMessageW` would overwrite pynput's own signature (`c_voidp` for the `MSG` pointer) and make pynput's message loop raise `ArgumentError`, killing the keyboard listener thread — the exact symptom of "tray works, hotkeys do not".
- The thread runs a `GetMessageW` loop; `WM_WTSSESSION_CHANGE` (`0x02B1`) is handled in the window procedure and reported through a callback. `PostThreadMessageW(thread_id, WM_QUIT)` ends the loop; teardown unregisters the WTS notification, destroys the window and unregisters the class. Class names are unique per instance (`CapturMDCSessionWatcher-<id>`), so start/stop cycles never reuse a stale window procedure.
- The thread runs a `GetMessageW` loop; `WM_WTSSESSION_CHANGE` (`0x02B1`) is handled in the window procedure and reported through a callback. `PostThreadMessageW(thread_id, WM_QUIT)` ends the loop; teardown unregisters the WTS notification, destroys the window and unregisters the class. Class names are unique per instance (`CapturMDCSessionWatcher-<id>`), so start/stop cycles never reuse a stale window procedure.
- `RESUME_EVENTS = {SESSION_CONNECT, CONSOLE_CONNECT, LOGON, UNLOCK, REMOTE_CONNECT}`; `App._on_session_change` forces `hotkeys.reattach(force=True)`, clears the blocked reason, calls `tray.refresh()` and notifies `Atajos reactivados` when the hook was actually re-armed. Lock/logoff events are ignored (no keys can be pressed anyway).
- If `wtsapi32` registration fails, the app keeps running: the keepalive below still recovers. A diagnostic line is printed to stderr.

**Keepalive watchdog (`hotkeys.py`)**

- `_touch()` records the last hook event in `_last_event`; `_last_reattach` records the last re-arm.
- `KEEPALIVE_INTERVAL = 20.0` s of total silence means the hook is probably dead (a dead hook receives nothing, so silence is the signal), and `reattach()` re-arms it. The watchdog thread checks every `WATCHDOG_INTERVAL = 5.0` s, so recovery is ≤ ~25 s even without session events (or when the listener thread died from an exception).
- `reattach(force=False)`: returns `False` when the listener is running, alive and the last event/reattach is fresher than the interval, so healthy hooks are never re-installed while typing. `force=True` is used by the session handler.
- `_restart_listener()` installs the **new** hook *before* stopping the old listener (pynput listeners cannot be restarted once stopped), so there is no blind window between hooks; only then it stops/joins the old listener (`join(timeout=2.0)`) and calls `reset()`. If installing the new hook fails, it drops the old one and retries once; the next watchdog tick tries again.
- `reattach()` defers (returns `False`) while a combination is in flight — a pending partial timer, keys still held, or `_full_fired` — so a re-arm never drops a capture that is mid-flight; the next tick re-arms once idle.
- `_sweep_stuck_keys()` forgets keys whose release event never arrived (missed releases leave a phantom modifier held forever and block every hotkey). It only sweeps after `STALE_KEYS_INTERVAL = 10.0` s of hook silence, so a combination being typed is never cleared.
- `stop()` sets `_stopping` first so the watchdog cannot resurrect a listener during shutdown, signals the stop event and joins the watchdog thread before stopping the hook.
- Shutdown order in `App._shutdown()`: session watcher → hotkeys → tray → settings.

---

## 5. Capture (`capture.py`)

### DPI and area

- `ensure_dpi_aware()` calls `SetProcessDPIAware()` so `mss` works in physical pixels.
- `get_virtual_monitor()` returns `mss.monitors[0]` (`left`, `top`, `width`, `height`), which spans all monitors, including negative offsets.
- `grab_full_image()` captures that area; `grab_region_image(region)` captures an arbitrary rectangle (API-level, not used by the current selection flow).
- Each capture opens a new `mss.MSS()` session (`with`), avoiding handles shared across threads.

### Saving

`save_image(image, dir, filename, fmt, quality)`:

- `PNG` or `JPEG` with `quality` clamped to 1–100 and `optimize=True`.
- Returns the absolute path.

### `CF_DIB` clipboard payload

`build_dib(image)` produces a `BITMAPINFOHEADER` (40 bytes) + pixels:

| Field | Value |
| --- | --- |
| `biSize` | 40 |
| `biWidth` | width |
| `biHeight` | height **positive** → bottom-up DIB |
| `biPlanes` | 1 |
| `biBitCount` | 24 |
| `biCompression` | `BI_RGB` (0) |
| `biSizeImage` | `stride * height` |

Critical details:

1. Windows 24 bpp BI_RGB stores channels as **B,G,R**; PIL stores R,G,B → channels are reversed with `Image.merge("RGB", tuple(reversed(rgb.split())))`.
2. With positive `biHeight` the buffer starts at the **last** scanline (bottom-up) → rows are appended in reverse order (`for y in range(height-1, -1, -1)`); otherwise the image appears vertically flipped.
3. Rows are aligned to 4 bytes: `stride = (width*3 + 3) & ~3`, padding with `\x00`.
4. `copy_image_to_clipboard`: `_open_clipboard()` retries 8 times with 50 ms delay (other apps hold the clipboard), `EmptyClipboard()`, `GlobalAlloc(GMEM_MOVEABLE, len)`, `GlobalLock`, `ctypes.memmove`, `GlobalUnlock` (only treated as a failure when `GetLastError() != 0`), `SetClipboardData(CF_DIB, hmem)`. On success the handle ownership transfers to the clipboard; on failure it is released with `GlobalFree`, and the clipboard is always closed in `finally`.
5. PNG is not used on the clipboard: `CF_DIB` is what Windows applications paste with correct colours and orientation.

---

## 6. Partial selection (`selection.py`)

Flow (`select_image(master, snapshot, monitor)`):

1. `App._capture_partial()` first calls `capture.grab_full_image()` → the **frozen snapshot**; nothing live is captured again.
2. `SelectionOverlay` creates a `tk.Toplevel` with `overrideredirect(True)`, geometry `width x height + left + top` of the virtual monitor, `-alpha = 1.0` (opaque) and `-topmost = True`.
3. Background: `ImageTk.PhotoImage(_tinted(snapshot))`, where `_tinted` blends the copy with `#0b1320` at 28 % (`Image.blend`) to signal frozen mode without hiding readable content. The reference is kept in `canvas.image` so Tk does not garbage-collect it.
4. centred hint text; `focus_force()` + `grab_set()` to capture mouse/keyboard.
5. Canvas events: `<ButtonPress-1>` → origin, `<B1-Motion>` → current point and `_draw()`, `<ButtonRelease-1>` → crop; `<Escape>` / `<KeyRelease-Escape>` → cancel.
6. `_draw()` draws only the dotted border (`dash=(6,4)`, `#00d0ff`, width 2) and a `W x H px` label. `stipple="50%"` is **not** used because Windows Tk raises `TclError: bitmap "50%" not defined`.
7. `_release`: sorts coordinates, `MIN_SELECTION = 6` px; too small → cancel. Valid → `self.region = {...}` and `self.image = snapshot.crop(...)` → the crop comes from the **snapshot**, not the live screen.
8. `gate` (`tk.StringVar`) is set to `"done"`; `master.wait_variable(gate)` returns to the mainloop thread.
9. `hide()` takes the overlay off screen (`withdraw` + `alpha 0.0` + `update_idletasks` + 100 ms) before writing the result; `destroy()` releases the grab, PhotoImage and window inside a `finally`.

---

## 7. Tray (`tray.py`)

- Menu: `Captura completa`, `Captura parcial`, `Configuración` (`default=True` → left click on the icon), `Pausar/Reanudar` (`checked=lambda item: self._is_paused()`), `Salir`.
- Each item calls `on_action(action)` → `App._post_action` → queue.
- `build_icon_image(paused)`: 32×32 RGBA camera, blue `#4fb3ff` when active / amber `#ffb84f` when paused with two white bars.
- `start(timeout=2.0)`: daemon thread running `icon.run()`, waiting until `icon.visible`.
- `refresh()`: redraws the icon, switches the tooltip to `CapturMDC (pausa)` and calls `icon.update_menu()` to refresh the dynamic tick.
- `notify()` is best-effort (exceptions are swallowed: notifications must not break a capture).

---

## 8. Settings window (`settings.py`)

- `ctk.CTkToplevel` on top of the hidden root; title `CapturMDC — Configuración`; `470x640`, `minsize 430x480`; `CTkScrollableFrame`.
- Theme: `CTkSegmentedButton` Dark/Light → live `ctk.set_appearance_mode()`.
- Folder: entry + `Buscar…` (`askdirectory(parent=self)`).
- Format: segmented `PNG`/`JPG`; the JPEG quality row is shown only for `JPG` (`grid()` / `grid_forget()`).
- Quality: slider 1–100 with a value label.
- Pattern / strftime / hotkeys: entries with placeholders.
- Partial delay: slider 0.05–1.5 (29 steps) → stored as `partial_delay` (no duplicate assignment that would ignore the slider).
- Autosave: checkbox + hint. When on, the hint reads "Siempre se copia al portapapeles … además se guarda el archivo" in gray; when off, it reads "Sólo se copia al portapapeles …: no se escribe ningún archivo" in red.
- `collect()` returns the full dict; `max_capture_timeout` and `pause_resume_transition` are preserved from `_cfg`.
- `_save()` runs `validate_config(..., strict=True)`; a `ValueError` is displayed in the red `error_label` and the window stays open. Only if validation succeeds it calls `on_save` (which persists and reconfigures the controller) and closes.
- `WM_DELETE_WINDOW` → `on_close` → `App._settings_closed()` (releases the hotkey block and calls `hotkeys.reset()`).

Applying new settings (`App._apply_config`): `config.save_config`, `self.cfg = validated`, prepare directory, `set_appearance_mode`, `hotkeys.set_hotkeys(full, partial, delay, timeout)`, `tray.refresh()`, notification `Configuración guardada`.

---

## 9. Data flows

### Full capture (hotkey or menu)

```
exact press (full) -> queue "capture_full" -> _dispatch -> allow predicates -> _capture_full
  _busy=True
  capture.grab_full_image()   # mss monitors[0], RGB
  _emit_image(image)
  _busy=False
```

`_emit_image(image)` is the single output path used by both capture types:

```
parts = []
if cfg["autosave"]:
    try: parts.append("Guardado: " + self._save_image(image))
    except Exception: parts.append("Error al guardar: ...")   # clipboard still attempted
try: capture.copy_image_to_clipboard(image); parts.append("Copiado al portapapeles")
except Exception: parts.append("Error al copiar al portapapeles: ...")
tray.notify(" · ".join(parts))
```

So autosave on = file **and** clipboard; autosave off = clipboard only. A failure in one output never prevents the other.

### Partial capture

```
exact press (partial) -> Timer after partial_delay -> queue "capture_partial"
  _busy=True, _selection_active=True
  snapshot = capture.grab_full_image()      # frozen
  monitor  = capture.get_virtual_monitor()
  image    = selection.select_image(root, snapshot, monitor)   # wait_variable
  image is None -> notify "Selección cancelada"
  else -> _emit_image(image)                # crop of the frozen image: clipboard (+ file if autosave)
  _selection_active=False, _busy=False
```

### Pause / resume
```
toggle_pause -> ignored if busy or in transition
  _paused = not _paused; _blocked_reason=None
  _transition_until = monotonic() + pause_resume_transition
  hotkeys.reset(); tray.refresh(); notify
```

### Shutdown

`_quit()` / `run()` `finally` → `_shutdown()`: `hotkeys.stop()`, `tray.stop()`, destroy settings; then `root.quit()`.

---

## 10. Error handling

| Case | Behaviour |
| --- | --- |
| Unreadable/corrupt `config.json` | Lenient load: per-key defaults |
| Writing `config.json` fails | stderr, capture still works in memory |
| Save folder not writable | Falls back to the default and notifies; if that also fails, the default string is used |
| File write fails during a capture | `Error al guardar: ...` notification; the clipboard copy is still attempted |
| Clipboard busy | 8 retries of 50 ms, then `Error al copiar al portapapeles: ...` notification; the file is still saved when autosave is on |
| `GlobalAlloc/Lock/SetClipboardData` failures | `GlobalFree` of the handle and `Error de captura: ...` notification |
| Empty image | `ValueError("La imagen capturada está vacía")` in `build_dib` |
| Alpha/topmost unsupported | `TclError` ignored (overlay still usable) |
| Session notification unavailable (`wtsapi32` fails) | stderr diagnostic; keepalive watchdog still re-arms the hook |
| Hook silent for 20 s (suspend, desktop switch, dead listener) | Watchdog stops the old listener and installs a new one, then `reset()` |
| `Listener` install/restart raises | Swallowed; retried on the next watchdog tick |
| Notification failures | Silenced |

---

## 11. Building the executable

`build_exe.cmd`:

```
python make_icon.py
python -m PyInstaller --noconfirm --clean --onefile --windowed --name CapturMDC --icon app.ico \
  --collect-data customtkinter \
  --exclude-module numpy --exclude-module asyncio --exclude-module multiprocessing \
  --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 \
  --hidden-import pynput._util.win32 --hidden-import pystray._win32 __main__.py
```

Why these flags:

- `--onefile --windowed`: a single `.exe`, no console (tray app).
- `--collect-data customtkinter`: CTk theme/colour JSON files.
- `--hidden-import ..._win32`: `pynput`/`pystray` pick their backend at runtime (dynamic import), so PyInstaller does not detect them.
- `--exclude-module numpy/asyncio/multiprocessing`: not used at runtime and saves ~12 MB.
- Result: `dist\CapturMDC.exe` ≈ 20.4 MB; start-up 2–3 s (bundle extraction).
- Artefacts: `build/`, `CapturMDC.spec`, `app.ico`.

Note: if the exe is running, the build cannot overwrite it (`PermissionError`); close the instance before rebuilding.

---

## 12. Verification performed

- Compilation: `python -m py_compile` of the 7 modules → OK.
- Hotkey normalization: aliases accepted; invalid combinations rejected (modifier-only, duplicates, bare letters, unsupported keys).
- Injected keys with `SendInput`:
  - `Ctrl+Alt+M` (quick tap) → `capture_partial` after the delay.
  - `Ctrl+Alt+Shift+M` → `capture_full` immediately.
  - `Ctrl+Alt+M` + `Shift` within the delay → partial cancelled, full fired.
  - Unsupported keys held → partial cancelled.
  - Blocked allow predicate → actions cancelled.
- Selection with synthetic canvas events (mouse injection via `SendInput` returns 0 in this environment): correct region, crop identical to the frozen snapshot, drag < 6 px cancels, `Esc` cancels.
- Clipboard: round-trip identical for pure colours, gradients, full screen and region; saved bytes and clipboard payload match; header `(40, W, H, 1, 24, 0)`.
- Frozen executable: imports of `pynput`, `pystray._win32`, `customtkinter`, `mss`, `win32clipboard/gui/api`, PIL OK; full cycle full → partial (overlay open, full ignored) → `Esc` → full again; clean shutdown.
- Session watcher: message-only window created, `WTSRegisterSessionNotification` succeeded, simulated `WM_WTSSESSION_CHANGE` delivered to the callback (unlock/logon/console connect), lock delivered but not treated as a resume event, `stop()` destroys the window and a second watcher instance can start in the same process.
- ctypes clash regression: before the fix, importing `session` turned pynput's `MessageLoop._GetMessage.argtypes[0]` into `LP_MSG` and its own call raised `ArgumentError` (listener thread dies, hotkeys silent); after the fix the argtypes stay `(c_void_p, c_void_p, c_ulong, c_ulong)` and no pynput error is logged for 12+ s with the watchdog running (checked in source and in the frozen exe).
- Keepalive: full/partial combos fire, then the hook was force-stopped to emulate a session change; the watchdog re-armed a new listener within ~3.5 s and the next combo fired again; `reattach(force=True)` re-armed immediately; `reattach()` on a fresh healthy hook returns `False` (no needless re-install); `stop()` leaves no live listener or watchdog thread.
- Stuck keys: pressing `Ctrl+Alt` plus an unsupported key without releasing them blocks both hotkeys; after the stale-keys sweep the state is empty and both hotkeys fire again; keys held while fresh are not swept.
- Dual output: with autosave on a full capture wrote `Screenshot_*.png` **and** updated the clipboard (`CF_DIB`, 24,883,240 bytes, header `(40, 3840, 2160, 1, 24, 0)`); with autosave off the clipboard updated again with no new file. A partial capture (auto-drag crop 320x220) wrote a 6,340-byte PNG and put the same crop on the clipboard (`CF_DIB`, 211,240 bytes, header `(40, 320, 220, 1, 24, 0)`).
- Keepalive: full/partial combos fire, then the hook was force-stopped to emulate a session change; the watchdog re-armed a new listener within ~3.5 s and the next combo fired again; `reattach(force=True)` re-armed immediately; `reattach()` on a fresh healthy hook returns `False` (no needless re-install); `stop()` leaves no live listener or watchdog thread.
- App integration: watcher active on start, `App._on_session_change(UNLOCK)` re-created the listener and a full capture saved a file afterwards; a second forced hook loss was recovered by the watchdog alone and a partial capture completed (3 files total, clean shutdown).

---

## 13. Limitations and known risks

- Exact matching: any extra unsupported held key invalidates a trigger.
- Supported base keys: `PrSc` and `a–z` with a modifier.
- One capture at a time (`_busy`); no queue.
- Keyboard hooks are per-session: after a fast user switch, the process stays in its own session/desktop, so each user session that needs hotkeys must run its own instance. Re-registering helps in the *current* session (suspend, lock, console reconnect), not in another user's session.
- Re-arming the hook while keys are held drops the held state (`reset()`), so the combination must be pressed again; this is why the keepalive only acts after a 20 s silence.
- The selection overlay covers the whole virtual screen; in multi-monitor setups with negative coordinates the geometry is derived from `monitors[0]`.
- `CF_DIB` delivers 24 bpp RGB without an alpha channel; PNG keeps the original on disk. The clipboard holds only the last capture (one clipboard, overwritten each time).
- Some third-party apps may interpret the DIB their own way (their own flipping/scaling); the payload follows the Windows specification.
- Freezing the screen means the partial capture does not reflect changes made after the key press (this is the intended behaviour).

---

## 14. Extension points

- New base keys: add a token to `MODIFIER_ALIASES`/`PYNPUT_NAME_TOKENS`/`VK_*_TOKENS` and to letter validation.
- New formats: extend `normalize_output_format` and `save_image` (e.g. WebP with Pillow).
- Copy a file to the clipboard: add `CF_HDROP`, or `CF_DIB` + `CF_BITMAP` in `capture.copy_image_to_clipboard`.
- Sound / pause hotkey: new action in `App._dispatch` + item in `tray.py`.
- Session events: extend `RESUME_EVENTS` or add `WM_DEVICE_BROADCAST`/power handling in `SessionWatcher._window_proc`.
- Keepalive tuning: `HotkeyController(keepalive_interval=..., watchdog_interval=...)` (defaults 20 s / 5 s); could be exposed as config keys.
- Without freezing the screen: replace `select_image(root, snapshot, monitor)` with a live selection + `grab_region_image(region)`.
