# CapturMDC implementation plan

> Paths use placeholders: `<PROJECT>` is the folder containing the project and its `.venv`.

## Scope
- Windows-only background tray app.
- Global hotkeys for full and partial screenshots.
- Hidden Tk/customtkinter root and mainloop with queue polling.
- Settings window opened from tray left click.
- Tray menu actions and pause/resume hotkey control.
- Capture output saved as PNG or JPG, or copied to clipboard when autosave is disabled.

## Modules
- `config.py`: JSON config load/save, defaults, validation, save directory checks, filename sanitization.
- `hotkeys.py`: hotkey normalization/validation and exact held-key listener controller.
- `capture.py`: DPI-aware full capture and Windows clipboard `CF_DIB` copy.
- `selection.py`: full virtual-screen partial selection overlay using plain Tk.
- `settings.py`: dark/light settings `CTkToplevel`.
- `tray.py`: pystray tray icon and Spanish menu.
- `__main__.py`: startup, queue polling, action dispatch, capture/save/clipboard/settings orchestration.
- `requirements.txt`: dependency list.

## Defaults
- Save path: `%USERPROFILE%\Pictures\CapturMDC`
- Filename pattern: `Screenshot_{timestamp}`
- Timestamp format: `%Y%m%d_%H%M%S`
- Output format: `png`
- JPEG quality: `90`
- Autosave: `true`
- Theme: `dark`
- Full hotkey: `Ctrl+PrSc`
- Partial hotkey: `PrSc`
- Partial delay: `0.25`
- Max capture timeout: `30`
- Pause/resume transition: `0.35`

## Hotkey rules
- Canonical form: modifiers first, base key last.
- Accepted bases: `PrSc`, letters `a-z`.
- Letters require `Ctrl`, `Alt`, or `Shift`.
- `PrSc` may be standalone or combined with modifiers.
- Exact held-key matching, not superset matching.
- Full hotkey is checked before partial hotkey.
- Partial hotkey schedules after delay and cancels on full exact match, unsupported keys held, busy/paused state, pause/resume transition, or timeout. Releasing keys does not cancel it, so a quick tap of the partial combination still fires after the delay.
- Unsupported held keys invalidate exact hotkey matching.
- Hotkey presses are ignored while busy, paused, settings open, selection active, or transition active.

## Capture rules
- Full capture uses `ctypes.windll.user32.SetProcessDPIAware()` and `mss.monitors[0]`.
- Image conversion uses `PIL.Image.frombytes("RGB", img.size, img.rgb)`.
- Partial capture first grabs the whole virtual screen and freezes it as the overlay background, so live/animated content cannot move while dragging.
- Partial overlay covers the full frozen snapshot (full virtual screen, including negative coordinates).
- Overlay shows the tinted frozen snapshot (opaque) with dotted selection borders; the crop comes from the frozen snapshot, not from a second live grab.
- Overlay is withdrawn before the result is written to disk or the clipboard.

## Settings rules
- Theme: dark/light.
- Save path.
- Output format: PNG/JPG.
- JPEG quality applies only when JPG is selected.
- Filename pattern and timestamp format.
- Full/partial hotkey validation.
- Autosave toggle: when disabled, clipboard copy uses Windows `CF_DIB`.

## Validation
- Syntax-check each module with the target Python executable.
- Basic import/runtime smoke checks for config defaults, hotkey normalization, filename build, capture image shape, and clipboard DIB builder.


# Objective
Implement the Windows-only background tray app CapturMDC with global full/partial screenshot hotkeys, PNG/JPG saving or Windows clipboard copy when autosave is disabled, Spanish tray actions, and a dark/light settings window without a visible main app window.
Important Details
Destination folder: <PROJECT>\CapturMDC.
Target interpreter: <PROJECT>\.venv\Scripts\python.exe.
Verified Python version: 3.14.6.
Config file path: %APPDATA%\CapturMDC\config.json.
Approved defaults:
Save path: %USERPROFILE%\Pictures\CapturMDC
Filename pattern without extension: Screenshot_{timestamp}
Timestamp format: %Y%m%d_%H%M%S
Output format: png
JPEG quality: 90
Autosave: true
Theme: dark
Full hotkey: Ctrl+PrSc
Partial hotkey: PrSc
Partial delay: 0.25
Max capture timeout: 30
Pause/resume transition: 0.35
Required modules:
config.py: JSON config load/save, defaults, validation, save-directory checks, filename sanitization.
hotkeys.py: hotkey normalization/validation and exact held-key listener/controller.
capture.py: DPI-aware full capture, region capture, PNG/JPG saving, and Windows clipboard CF_DIB copy.
selection.py: full virtual-screen partial selection overlay using plain Tk.
settings.py: dark/light settings CTkToplevel.
tray.py: pystray tray icon and Spanish menu actions.
__main__.py: startup, queue polling, action dispatch, hotkey/tray/settings orchestration, save-path validation.
requirements.txt: dependency list.
Tray menu must include exact Spanish items: Captura completa, Captura parcial, Configuración, Pausar/Reanudar, Salir.
Tray left click must open Settings immediately via default menu item Configuración.
Settings must support dark/light theme, save path, PNG/JPG format, JPEG quality only when JPG is selected, filename pattern, timestamp format, hotkeys, and autosave toggle.
Hotkey validation rules:
Canonical form: modifiers first, base key last.
Canonical display order: Ctrl, Alt, Shift, then base.
Accepted bases: PrSc, letters a-z.
Letters require Ctrl, Alt, or Shift.
PrSc may be standalone or combined with modifiers.
Reject duplicate modifiers, modifiers-only hotkeys, unsupported keys, and bare letters.
Normalize aliases: prsc, printscreen, print_screen, print screen, ctrl, control, ctl, alt, shift.
Letters are case-insensitive.
Hotkey implementation decisions:
config.py imports hotkey validation/normalization from hotkeys.py.
hotkeys.py must not import config.py to avoid circular imports.
Runtime canonical tokens may be lowercase: ctrl, alt, shift, prsc, letters.
Exact held-key matching uses counts per canonical token and unsupported-key counts, not superset matching.
Unsupported held keys invalidate exact hotkey matching.
Full hotkey is checked before partial hotkey.
Partial hotkey schedules after delay and cancels if full hotkey becomes exact, keys release, busy/paused state changes, pause/resume transition is active, unsupported keys are held, or timeout occurs.
Hotkey presses are ignored while capture, settings, partial selection, paused state, transition, or other busy operations are active.
Controller should use pynput.keyboard.Listener, cancelable partial threading.Timer, _full_fired, _partial_timer, _partial_fired, and an allow-action predicate.
Capture implementation decisions:
DPI-awareness method: ctypes.windll.user32.SetProcessDPIAware().
Full capture uses mss.MSS().monitors[0] as the virtual multi-monitor screen.
Earlier runtime DPI mismatch observed:
mss.MSS().monitors[0] returned {'left': 0, 'top': 0, 'width': 3840, 'height': 2160}.
win32api.GetSystemMetrics virtual metrics returned x=0, y=0, w=2560, h=1440.
Clipboard image copy must use Windows CF_DIB, not a PNG file.
CF_DIB must contain bottom-up padded RGB rows and a BITMAPINFOHEADER.
Clipboard path should use win32clipboard, GlobalAlloc, GlobalLock, memmove/MoveMemory, GlobalUnlock, SetClipboardData(CF_DIB, hmem), and safe clipboard cleanup.
Partial-selection decisions:
Partial overlay must cover the full virtual screen from mss.MSS().monitors[0], including negative coordinates.
Overlay should be semitransparent with dotted selection borders.
Overlay must be hidden before capture to avoid screenshot artifacts.
Selection result can be stored via tkinter.Variable and root.wait_variable.
Runtime architecture decisions:
Hidden CTk root/mainloop with queue polling via after.
Settings as CTkToplevel.
Partial selection as plain tk.Toplevel attached to the hidden root.
Tray callbacks and hotkey listener actions put actions into a thread-safe queue consumed by the Tk mainloop.
Action queue items should include at least capture_full, capture_partial, open_settings, toggle_pause, and quit.
Allow-action predicate should block hotkeys while exiting, busy, paused, settings open, selection active, or transition active.
Tray capture actions should be allowed while paused unless busy/transition blocks them.
Tray pause/resume transition should use pause_resume_transition seconds via time.monotonic().
Import strategy:
__main__.py should support direct script and package execution.
Insert the folder into sys.path when running as a script or fallback absolute local imports.
Modules should use absolute local imports where practical.
Verified dependency versions in .venv:
customtkinter 6.0.0.
mss 10.2.0.
pillow 12.3.0.
pystray 0.19.5.
pywin32 312.
pywin32/win32gui available.
pynput 1.8.2.
pystray.Icon API supports run(self, setup=None) and stop(); constructor signature observed as (self, *args, **kwargs).
pystray.MenuItem signature:
MenuItem(text, action, checked=None, radio=False, default=False, visible=True, enabled=True).
pystray._win32 left-button behavior:
WM_LBUTTONUP activates the icon.
pystray._base.Icon.__call__ calls the icon menu.
pystray._base.Menu.__call__ invokes the menu item with default=True.
Runtime inspection confirmed pynput Print Screen token is pynput.keyboard.Key.print_screen.
Runtime inspection confirmed pynput.keyboard.Special does not exist in installed pynput 1.8.2.
Windows may intercept PrSc for Snipping Tool or clipboard capture; users can configure Ctrl+PrSc, Alt+PrSc, or modifier+letter hotkeys if needed.
Auto-save disabled behavior: capture copies the image to Windows clipboard instead of saving a file.
Save directory must be auto-created and validated as writable at startup.
Filename validation must sanitize invalid Windows filename/control characters, preserve {timestamp}, and choose extension from output format.
Invalid filename characters include <>:"/\|?* and control characters.
Config load/save must use JSON, atomic replacement if possible, and fall back to defaults for invalid values.
Settings validation should use strict validation that raises ValueError for invalid hotkey/filename/timestamp/save-path values and show an error message instead of closing.
Settings quality slider should only be visible when format is jpg; hide via grid_forget() and show via grid().
Customtkinter API check verified:
hasattr(ctk.CTkSegmentedButton, 'set') is True.
hasattr(ctk.CTkSlider, 'set') is True.
hasattr(ctk.CTkCheckBox, 'select') is True.
hasattr(ctk.CTkScrollableFrame, 'grid') is True.
Command strategy: heredoc-style python - <<'PY' failed under PowerShell parser; avoid heredoc-style commands and prefer python -m py_compile or simple python -c commands using semicolons.
Work State
Completed
Virtual environment verified:
<PROJECT>\.venv\Scripts\python.exe.
Python version 3.14.6.
Dependencies verified in .venv:
customtkinter 6.0.0.
mss 10.2.0.
pillow 12.3.0.
pystray 0.19.5.
pywin32 312.
win32gui.
pynput 1.8.2.
Hotkey behavior requirements and validation rules approved.
Tray interaction behavior approved: left click opens Settings via default menu item.
Clipboard behavior approved: disabled autosave copies image to Windows clipboard using CF_DIB.
Runtime facts for pynput Print Screen token and DPI-awareness method confirmed.
Customtkinter widget API attributes verified.
Module implementation design has been outlined:
config.py: defaults, config path, JSON load/save, atomic write, save-path validation, filename sanitization, hotkey validation integration.
hotkeys.py: canonical normalization/validation, exact held-key counts, unsupported-key invalidation, full-before-partial matching, partial timer cancellation.
capture.py: DPI-awareness, full virtual-screen mss capture, CF_DIB clipboard copy with bottom-up padded RGB rows.
selection.py: full virtual-screen partial overlay using plain Tk and dotted borders.
settings.py: dark/light CTkToplevel settings window with dynamic quality slider visibility.
tray.py: pystray tray icon with Spanish menu actions and pause/resume state updates.
__main__.py: hidden root/mainloop, queue polling, action dispatch, hotkey/tray/settings orchestration, startup save-path validation.
requirements.txt: dependency list.
Folder inspection performed:
<PROJECT>\CapturMDC contains only config.py and plan.md.
<PROJECT>\CapturMDC\config.py remains empty; prior read confirmed 0 lines.
pystray.MenuItem signature inspected successfully:
MenuItem(text, action, checked=None, radio=False, default=False, visible=True, enabled=True).
pystray.MenuItem source inspected in conversation:
MenuItem is immutable.
checked is a property returning self._checked(self).
_checked defaults to lambda _: None if not callable.
MenuItem.__call__ calls self._action(icon, self) when action is not a Menu.
plan.md beginning inspected: scope, modules, defaults, hotkey rules, and partial hotkey cancellation behavior shown before truncation.
Active
No source files have been written since the prior implementation design was finalized.
Pending module creation:
config.py
hotkeys.py
capture.py
selection.py
settings.py
tray.py
__main__.py
requirements.txt
Syntax and basic runtime validation not yet run.
Pause/resume tray menu state-update mechanism is being finalized:
Direct checked=True assignment is not supported.
checked callable is a viable dynamic state mechanism based on inspected source.
Exact menu refresh mechanism still needs confirmation or a fallback design.
Full contents of plan.md have not been captured because the read result was truncated after the hotkey rules section.
Blocked
pystray.MenuItem.checked cannot be assigned directly.
Prior failed command:
& "<PROJECT>\.venv\Scripts\python.exe" -c "import inspect, pystray; print(inspect.signature(pystray.Icon.__init__)); print(inspect.signature(pystray.Icon.run)); print(inspect.signature(pystray.MenuItem.__init__)); m=pystray.MenuItem('x', lambda item: None); print(hasattr(m,'checked')); m.checked=True; print(m.checked); print(hasattr(pystray.Icon,'notify'))"
Error:
AttributeError: property 'checked' of 'MenuItem' object has no setter
The command did not reach the final hasattr(pystray.Icon,'notify') check because it failed earlier.
The newer pystray inspection result was truncated before confirming Icon.notify or menu-refresh behavior.
Full remaining plan.md details after the hotkey rules are not available from the truncated read; implement using approved summary details unless additional plan details are needed.
Next Move
Implement <PROJECT>\CapturMDC\config.py with defaults, config path, JSON load/save, atomic write, save-path validation, filename sanitization, and strict/non-strict validation helpers.
Implement <PROJECT>\CapturMDC\hotkeys.py with canonical hotkey normalization/validation and exact held-key listener/controller behavior.
Implement <PROJECT>\CapturMDC\capture.py with DPI-aware full capture, region capture, image saving, and Windows CF_DIB clipboard copy.
Implement <PROJECT>\CapturMDC\selection.py with full virtual-screen partial selection overlay.
Implement <PROJECT>\CapturMDC\settings.py with dark/light settings CTkToplevel, dynamic JPG quality visibility, and strict validation.
Implement <PROJECT>\CapturMDC\tray.py with pystray tray icon, Spanish menu actions, default Configuración behavior, and a supported pause/resume state-update mechanism using checked callable plus menu refresh or text fallback as needed.
Implement <PROJECT>\CapturMDC\__main__.py with hidden CTk root/mainloop, queue polling, action dispatch, hotkey/tray/settings orchestration, and startup save-path validation.
Create <PROJECT>\CapturMDC\requirements.txt listing customtkinter, mss, pillow, pystray, pywin32, and pynput.
Validate syntax from <PROJECT>\CapturMDC with: & "<PROJECT>\.venv\Scripts\python.exe" -m py_compile config.py hotkeys.py capture.py selection.py settings.py tray.py __main__.py
Run simple python -c smoke checks for config defaults, hotkey normalization, filename building, capture image size, and CF_DIB builder length, avoiding heredoc-style commands.
Relevant Files
<PROJECT>\CapturMDC: project destination folder.
<PROJECT>\CapturMDC\plan.md: approved implementation plan; beginning read/truncated after hotkey rules, needs full details if remaining design specifics are required.
<PROJECT>\CapturMDC\config.py: currently empty; to be implemented as config module.
<PROJECT>\CapturMDC\hotkeys.py: to implement hotkey normalization, validation, and exact held-key listener behavior.
<PROJECT>\CapturMDC\capture.py: to implement DPI-aware full capture and Windows clipboard CF_DIB copy.
<PROJECT>\CapturMDC\selection.py: to implement full virtual-screen partial selection overlay.
<PROJECT>\CapturMDC\settings.py: to implement dark/light settings CTkToplevel.
<PROJECT>\CapturMDC\tray.py: to implement pystray tray icon and Spanish menu actions.
<PROJECT>\CapturMDC\__main__.py: to implement hidden root/mainloop, queue polling, action dispatch, and orchestration.
<PROJECT>\CapturMDC\requirements.txt: to list dependencies.
<PROJECT>\.venv\Scripts\python.exe: target interpreter for syntax and runtime validatio