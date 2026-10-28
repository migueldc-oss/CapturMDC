# User manual — CapturMDC

A Windows tray (system tray) app that captures the whole screen or a selected area, saves it as PNG/JPG, or copies it to the clipboard. There is no main window: everything is driven from the tray icon and global hotkeys.

---

## 1. Requirements

- Windows 10/11 (64-bit).
- The executable needs no Python: `dist\CapturMDC.exe` is self-contained.
- To run the source: Python 3.12+ plus the dependencies in `requirements.txt`.

---

## 2. Installation and startup

Paths below use placeholders: `<PROJECT>` is the folder containing the project (and its `.venv`), `<USERNAME>` is your Windows user name.

### From the executable (recommended)

1. Run `<PROJECT>\CapturMDC\dist\CapturMDC.exe`.
2. A blue camera icon appears in the tray (2–3 seconds; the *onefile* bundle unpacks at start-up).
3. No window opens: it runs in the background.

### From the source

```powershell
cd <PROJECT>
.\.venv\Scripts\python.exe -m CapturMDC
```

### Rebuild the executable

```powershell
<PROJECT>\CapturMDC\build_exe.cmd
```

Requires `pyinstaller` (`requirements-build.txt`).

---

## 3. Tray icon

| State | Icon |
| --- | --- |
| Active | Blue camera (`#4fb3ff`) |
| Paused | Amber camera (`#ffb84f`) with two white bars |
| Tooltip | `CapturMDC` / `CapturMDC (pausa)` |

**Left click** → opens **Configuración** (Settings) directly.
**Right click** → opens the menu (labels stay in Spanish by design):

| Menu item | What it does |
| --- | --- |
| `Captura completa` | Captures the whole virtual screen (all monitors) |
| `Captura parcial` | Freezes the screen, then lets you drag a selection box |
| `Configuración` | Opens the settings window |
| `Pausar/Reanudar` | Toggles the paused state (shown ticked when paused) |
| `Salir` | Quits the app |

Menu actions stay available while **paused**; only the keyboard hotkeys are blocked.

---

## 4. Hotkeys

Defaults:

| Capture | Default hotkey |
| --- | --- |
| Full | `Ctrl+PrSc` |
| Partial | `PrSc` |

Hotkey syntax (aliases are accepted):

- Canonical order: modifiers first, base key last → `Ctrl+Alt+Shift+PrSc`, `Ctrl+Alt+M`.
- Valid modifiers: `Ctrl`, `Alt`, `Shift` (aliases: `control`, `ctl`).
- Base key: `PrSc` (aliases: `printscreen`, `print_screen`, `print screen`) or a letter `a–z`.
- Letters **require** at least one modifier: `Ctrl+A` is valid, bare `A` is rejected.
- Rejected: modifier-only combinations (`Ctrl+Alt`), repeated modifiers (`Ctrl+Ctrl+M`), unsupported keys (F1, Space, arrows…), bare letters.
- On save, the window shows the normalized text (e.g. `print screen` → `PrSc`, `ctl+a` → `Ctrl+A`).

Behaviour when full and partial share keys (e.g. partial `Ctrl+Alt+M`, full `Ctrl+Alt+Shift+M`):

- The **full capture fires immediately** once the exact combination is held.
- The **partial capture fires after the configured delay**; if `Shift` appears during that delay, the partial is cancelled and only the full one fires.
- Releasing the keys does **not** cancel the partial: a quick tap still produces the capture.
- If the delay is too short to add the extra modifier, raise it (see section 5).

> Windows may reserve `PrSc` for Snipping Tool. If bare `PrSc` does not work, use `Ctrl+PrSc`, `Alt+PrSc`, or a modifier + letter (`Ctrl+Alt+F`, `Ctrl+Alt+S`).

---

## 5. Settings window

Fields and valid ranges:

| Field | Values / range | Default |
| --- | --- | --- |
| Theme | `Dark`, `Light` | `dark` |
| Save folder | Absolute writable path (`Buscar…` button) | `%USERPROFILE%\Pictures\CapturMDC` |
| Output format | `PNG`, `JPG` | `png` |
| JPEG quality (1–100) | Slider; **only shown when the format is JPG** | 90 |
| Filename pattern (no extension) | Must contain `{timestamp}` | `Screenshot_{timestamp}` |
| Date format (strftime) | e.g. `%Y%m%d_%H%M%S` | `%Y%m%d_%H%M%S` |
| Full capture hotkey | See rules in section 4 | `Ctrl+PrSc` |
| Partial capture hotkey | See rules in section 4 | `PrSc` |
| Partial capture delay (s) | 0.05–1.50 | 0.25 |
| Autosave to file | On/off | On |

`max_capture_timeout` (1–300 s) and `pause_resume_transition` (0–5 s) have no widget in the window: edit them in `config.json`.

**Save**: if a value is invalid, the window **does not close** and shows the error in red below the buttons. `Cancelar` (Cancel) or closing the window discards changes.

While the settings window is open, hotkeys are blocked (notified at most once every 2.5 s).

### Without autosave

If you turn *Autoguardar en archivo* off, the capture is copied to the **Windows clipboard** as an image (`CF_DIB`) and you can paste it (`Ctrl+V`) into Paint, Word, Slack, email, etc. The red hint line indicates that no file will be written.

---

## 6. Partial capture (frozen screen)

1. Pressing the hotkey (or `Captura parcial` in the menu) first takes a copy of the entire screen.
2. That copy is shown full-screen, slightly darkened, covering everything below it: videos, animations and movement **do not change** while you select.
3. Drag with the left button to draw the dotted box; the size in px is displayed.
4. On release, the **frozen image** is cropped (not the live screen) and saved or copied to the clipboard.
5. `Esc` cancels the selection. A drag smaller than 6 px also cancels.

If the box covered something you wanted to see, press `Esc` and capture again.

---

## 7. Where images are stored

- Folder: the configured one (default `%USERPROFILE%\Pictures\CapturMDC`).
- Name: pattern + timestamp built from the chosen strftime format.
  With defaults: `Screenshot_20261028_172955.png`.
- Invalid characters (`< > : " / \ | ? *`) are stripped from the name; reserved Windows names (`CON`, `PRN`, `AUX`, `NUL`, `COM1–9`, `LPT1–9`) are not used as the final name.

---

## 8. Pause / resume

- `Pausar/Reanudar` (menu) toggles the state; the icon turns amber and the tooltip becomes `CapturMDC (pausa)`.
- While paused, keyboard hotkeys do not capture; the menu can still capture manually.
- There is a short transition (0.35 s by default) where captures are blocked, to avoid accidental triggers during the change.

---

## 9. Notifications

The tray shows short messages:

- `Guardado: C:\...\Screenshot_...png` (saved)
- `Copiado al portapapeles` (copied to clipboard)
- `Selección cancelada` (selection cancelled)
- `Capturas en pausa` / `Capturas activas` (paused / active)
- `Configuración guardada` (settings saved)
- Blocked states (at most once every 2.5 s): `Captura en curso, espera a que termine`, `Capturas en pausa: usa Pausar/Reanudar en el menú de la bandeja`, `Ventana de configuración abierta: los atajos están bloqueados`, `Selección parcial en curso`, `Cambio de pausa/reanudar en curso`
- Errors: `Error de captura: …`, `Error de selección: …`

---

## 10. Configuration file

```
%APPDATA%\CapturMDC\config.json
%USERPROFILE%\AppData\Roaming\CapturMDC\config.json
```

It is created with the defaults on first run. You can edit it with any editor: invalid values are replaced by the default on load. Example:

```json
{
  "save_path": "C:\\Users\\<USERNAME>\\Pictures\\CapturMDC",
  "output_format": "png",
  "jpeg_quality": 90,
  "autosave": true,
  "theme": "dark",
  "filename_pattern": "Screenshot_{timestamp}",
  "timestamp_format": "%Y%m%d_%H%M%S",
  "full_hotkey": "Ctrl+Alt+F",
  "partial_hotkey": "Ctrl+Alt+A",
  "partial_delay": 0.25,
  "max_capture_timeout": 30.0,
  "pause_resume_transition": 0.35
}
```

Changes made in the file take effect after restarting the app (changes made in the settings window apply immediately).

---

## 11. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Icon does not appear | Wait 2–3 s (onefile start-up). If it persists, run the source to see console errors |
| Bare `PrSc` captures nothing | Windows reserves `PrSc` for Snipping Tool: use `Ctrl+PrSc` or modifier + letter |
| Partial fires when you wanted full | Raise *Partial capture delay* (0.3–0.6 s) and press `Shift` before releasing |
| Nothing captures, "Captura en curso" shown | A previous capture is still active (selection open or save in progress); wait or press `Esc` |
| Hotkeys do not work with `AltGR` | `AltGR` is treated as `Alt` |
| Pasted image is empty | Another app holds the clipboard; retry (8 retries of 50 ms) |
| Save folder not writable | Falls back to `%USERPROFILE%\Pictures\CapturMDC` and notifies |
| You want the frozen screen text clearly visible | Press `Esc` and capture again; the overlay darkens by 28 % to signal frozen mode |

---

## 12. Known limitations

- Windows only (tray, `CF_DIB` clipboard, DPI).
- Hotkeys limited to `PrSc` and letters with modifiers.
- One capture at a time (no capture queue).
- The partial capture uses the full virtual screen (monitors with negative offsets included); the overlay covers that area.
