"""Settings window (CTkToplevel) for CapturMDC with dark/light theme support."""

from __future__ import annotations

import tkinter as tk
from tkinter.filedialog import askdirectory
from typing import Any, Callable, Dict, Optional

import customtkinter as ctk

from config import DEFAULTS, validate_config

FORMAT_LABELS = ("PNG", "JPG")
THEME_LABELS = ("Dark", "Light")
ERROR_COLOR = "#ff6b6b"
HINT_COLOR = "gray"


class SettingsWindow(ctk.CTkToplevel):
    """Settings window; strict validation keeps the window open on errors."""

    def __init__(
        self,
        master: ctk.CTk,
        cfg: Dict[str, Any],
        on_save: Callable[[Dict[str, Any]], None],
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        ctk.set_appearance_mode(str(cfg.get("theme", DEFAULTS["theme"])))
        super().__init__(master)

        self._cfg = dict(cfg)
        self._on_save = on_save
        self._on_close_cb = on_close
        self._row = 0

        self.title("CapturMDC — Configuración")
        self.geometry("470x640")
        self.minsize(430, 480)
        self.protocol("WM_DELETE_WINDOW", self._handle_close)
        self.lift()

        body = ctk.CTkScrollableFrame(self, label_text="CapturMDC")
        body.pack(fill="both", expand=True, padx=12, pady=12)
        body.grid_columnconfigure(0, weight=1)

        # ------------------------------------------------------------------ theme
        self._add_label(body, "Tema")
        self.theme_var = tk.StringVar(value=str(cfg.get("theme", DEFAULTS["theme"])).capitalize())
        self.theme_button = ctk.CTkSegmentedButton(body, values=list(THEME_LABELS), command=self._apply_theme)
        self.theme_button.set(self.theme_var.get())
        self._add_widget(body, self.theme_button, pady=(0, 10))

        # -------------------------------------------------------------- save path
        self._add_label(body, "Carpeta de guardado")
        self.save_path_var = tk.StringVar(value=str(cfg.get("save_path", DEFAULTS["save_path"])))
        path_row = ctk.CTkFrame(body, fg_color="transparent")
        path_row.grid_columnconfigure(0, weight=1)
        self.save_path_entry = ctk.CTkEntry(path_row, textvariable=self.save_path_var)
        self.save_path_entry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(path_row, text="Buscar…", width=88, command=self._browse).grid(
            row=0, column=1, padx=(8, 0)
        )
        self._add_widget(body, path_row, pady=(0, 10))

        # -------------------------------------------------------------- format
        self._add_label(body, "Formato de salida")
        self.format_var = tk.StringVar(value=str(cfg.get("output_format", DEFAULTS["output_format"])).upper())
        self.format_button = ctk.CTkSegmentedButton(body, values=list(FORMAT_LABELS), command=self._on_format_change)
        self.format_button.set(self.format_var.get())
        self._add_widget(body, self.format_button, pady=(0, 10))

        # ------------------------------------------------------- JPEG quality row
        self.quality_frame = ctk.CTkFrame(body, fg_color="transparent")
        self.quality_frame.grid_columnconfigure(0, weight=1)
        self.quality_title = ctk.CTkLabel(self.quality_frame, text="Calidad JPEG (1–100)", anchor="w")
        self.quality_title.grid(row=0, column=0, sticky="w")
        self.quality_var = tk.DoubleVar(value=float(cfg.get("jpeg_quality", DEFAULTS["jpeg_quality"])))
        self.quality_slider = ctk.CTkSlider(
            self.quality_frame,
            from_=1,
            to=100,
            number_of_steps=99,
            variable=self.quality_var,
            command=self._on_quality_change,
        )
        self.quality_slider.set(float(self.quality_var.get()))
        self.quality_slider.grid(row=1, column=0, sticky="ew")
        self.quality_value_label = ctk.CTkLabel(
            self.quality_frame,
            text=str(int(round(self.quality_var.get()))),
            text_color=HINT_COLOR,
        )
        self.quality_value_label.grid(row=1, column=1, padx=(8, 0))
        self.quality_frame_row = self._add_widget(body, self.quality_frame, pady=(0, 10))

        # ------------------------------------------------------------ filename
        self._add_label(body, "Patrón de nombre (sin extensión)")
        self.pattern_var = tk.StringVar(value=str(cfg.get("filename_pattern", DEFAULTS["filename_pattern"])))
        self._add_widget(
            body,
            ctk.CTkEntry(body, textvariable=self.pattern_var, placeholder_text="Screenshot_{timestamp}"),
            pady=(0, 10),
        )

        self._add_label(body, "Formato de fecha (strftime)")
        self.timestamp_var = tk.StringVar(value=str(cfg.get("timestamp_format", DEFAULTS["timestamp_format"])))
        self._add_widget(
            body,
            ctk.CTkEntry(body, textvariable=self.timestamp_var, placeholder_text="%Y%m%d_%H%M%S"),
            pady=(0, 10),
        )

        # -------------------------------------------------------------- hotkeys
        self._add_label(body, "Atajo captura completa")
        self.full_hotkey_var = tk.StringVar(value=str(cfg.get("full_hotkey", DEFAULTS["full_hotkey"])))
        self._add_widget(body, ctk.CTkEntry(body, textvariable=self.full_hotkey_var, placeholder_text="Ctrl+PrSc"), pady=(0, 8))

        self._add_label(body, "Atajo captura parcial")
        self.partial_hotkey_var = tk.StringVar(value=str(cfg.get("partial_hotkey", DEFAULTS["partial_hotkey"])))
        self._add_widget(body, ctk.CTkEntry(body, textvariable=self.partial_hotkey_var, placeholder_text="PrSc"), pady=(0, 8))

        self._add_widget(
            body,
            ctk.CTkLabel(
                body,
                text="Formato: Ctrl+Alt+Shift+PrSc o Ctrl+A. Windows puede reservar PrSc para el Recorte.",
                text_color=HINT_COLOR,
                wraplength=420,
                justify="left",
            ),
            pady=(0, 12),
        )

        # ------------------------------------------------------- partial delay
        self._add_label(body, "Retardo de captura parcial (s)")
        self.delay_var = tk.DoubleVar(value=float(cfg.get("partial_delay", DEFAULTS["partial_delay"])))
        delay_row = ctk.CTkFrame(body, fg_color="transparent")
        delay_row.grid_columnconfigure(0, weight=1)
        self.delay_slider = ctk.CTkSlider(
            delay_row,
            from_=0.05,
            to=1.5,
            number_of_steps=29,
            variable=self.delay_var,
            command=lambda value: self.delay_value_label.configure(text=f"{float(value):.2f}"),
        )
        self.delay_slider.set(float(self.delay_var.get()))
        self.delay_slider.grid(row=0, column=0, sticky="ew")
        self.delay_value_label = ctk.CTkLabel(delay_row, text=f"{float(self.delay_var.get()):.2f}", text_color=HINT_COLOR)
        self.delay_value_label.grid(row=0, column=1, padx=(8, 0))
        self._add_widget(body, delay_row, pady=(0, 6))
        self._add_widget(
            body,
            ctk.CTkLabel(
                body,
                text="Si el atajo completo incluye el parcial (Ctrl+Alt+M → Ctrl+Alt+Shift+M), sube este retardo para pulsar Shift antes de que se dispare la captura parcial.",
                text_color=HINT_COLOR,
                wraplength=420,
                justify="left",
            ),
            pady=(0, 12),
        )

        # -------------------------------------------------------------- autosave
        self.autosave_var = tk.BooleanVar(value=bool(cfg.get("autosave", DEFAULTS["autosave"])))
        self.autosave_check = ctk.CTkCheckBox(
            body,
            text="Autoguardar en archivo",
            variable=self.autosave_var,
            command=self._on_autosave_change,
        )
        self._add_widget(body, self.autosave_check, pady=(0, 6))

        self.clipboard_hint = ctk.CTkLabel(
            body,
            text="",
            text_color=HINT_COLOR,
            wraplength=420,
            justify="left",
        )
        self._add_widget(body, self.clipboard_hint, pady=(0, 12))

        # --------------------------------------------------------------- actions
        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(actions, text="Guardar", command=self._save).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            actions,
            text="Cancelar",
            fg_color="transparent",
            border_width=1,
            command=self._handle_close,
        ).grid(row=0, column=1, padx=(8, 0))
        self._add_widget(body, actions, pady=(4, 6))

        self.error_label = ctk.CTkLabel(body, text="", text_color=ERROR_COLOR, wraplength=420, justify="left")
        self._add_widget(body, self.error_label, pady=(2, 6))

        self._show_quality(self.format_var.get() == "JPG")
        self._on_autosave_change()

    # --------------------------------------------------------------- grid helper
    def _add_label(self, parent: ctk.CTkScrollableFrame, text: str) -> int:
        row = self._row
        ctk.CTkLabel(parent, text=text, anchor="w").grid(row=row, column=0, sticky="w")
        self._row += 1
        return row

    def _add_widget(self, parent: ctk.CTkScrollableFrame, widget: Any, pady: tuple[int, int] = (0, 0)) -> int:
        row = self._row
        widget.grid(row=row, column=0, sticky="ew", pady=pady)
        self._row += 1
        return row

    # -------------------------------------------------------------- visibility
    def _show_quality(self, visible: bool) -> None:
        if visible:
            self.quality_frame.grid(row=self.quality_frame_row, column=0, sticky="ew", pady=(0, 10))
        else:
            self.quality_frame.grid_forget()

    # ---------------------------------------------------------------- callbacks
    def _apply_theme(self, value: str) -> None:
        self.theme_var.set(value)
        ctk.set_appearance_mode(str(value).lower())

    def _on_format_change(self, value: str) -> None:
        self.format_var.set(value)
        self._show_quality(str(value).upper() == "JPG")

    def _on_quality_change(self, value: float) -> None:
        self.quality_value_label.configure(text=str(int(round(float(value)))))

    def _on_autosave_change(self) -> None:
        enabled = bool(self.autosave_var.get())
        self.clipboard_hint.configure(
            text=(
                "Siempre se copia al portapapeles de Windows (CF_DIB); con autoguardar además se guarda el archivo."
                if enabled
                else "Sólo se copia al portapapeles de Windows (CF_DIB): no se escribe ningún archivo."
            ),
            text_color=HINT_COLOR if enabled else ERROR_COLOR,
        )

    def _browse(self) -> None:
        try:
            selected = askdirectory(title="Carpeta de guardado", parent=self)
        except Exception:  # pragma: no cover - dialog failure is non-fatal
            return
        if selected:
            self.save_path_var.set(selected)

    # ------------------------------------------------------------------- values
    def collect(self) -> Dict[str, Any]:
        return {
            "theme": str(self.theme_var.get()).lower(),
            "save_path": self.save_path_var.get(),
            "output_format": str(self.format_var.get()).lower(),
            "jpeg_quality": int(round(float(self.quality_var.get()))),
            "filename_pattern": self.pattern_var.get(),
            "timestamp_format": self.timestamp_var.get(),
            "full_hotkey": self.full_hotkey_var.get(),
            "partial_hotkey": self.partial_hotkey_var.get(),
            "autosave": bool(self.autosave_var.get()),
            "partial_delay": float(self.delay_var.get()),
            "max_capture_timeout": self._cfg.get("max_capture_timeout", DEFAULTS["max_capture_timeout"]),
            "pause_resume_transition": self._cfg.get("pause_resume_transition", DEFAULTS["pause_resume_transition"]),
        }

    def _save(self) -> None:
        try:
            validated = validate_config(self.collect(), strict=True)
        except ValueError as exc:
            self._show_error(str(exc))
            return
        self._show_error("")
        try:
            self._on_save(validated)
        except Exception as exc:
            self._show_error(f"No se pudo guardar la configuración: {exc}")
            return
        self._handle_close()

    def _show_error(self, message: str) -> None:
        self.error_label.configure(text=message)

    def _handle_close(self) -> None:
        callback = self._on_close_cb
        if callback is not None:
            callback()
        try:
            self.destroy()
        except tk.TclError:  # pragma: no cover - already destroyed
            pass
