"""
Privacy-Focused Desktop Assistant — Dev Mode UI
A sleek, minimalist control panel built with tkinter.
Includes full debug panels, log console, and dev tools.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import time
import datetime
from PIL import Image, ImageTk

from src.capture import ScreenCapture
from src.ocr import OCRProcessor
from src.analyzer import ContextAnalyzer, Insight
from src.voice import VoiceFeedback
from src.overlay import OverlayWindow, OverlayRect
from src.region_selector import RegionSelector

from src.ui_theme import C, make_font, RoundedButton


# ────────────────────────────── main window ────────────────────────────────

class AssistantUI:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("BH-AI  ·  Dev Mode")
        self.root.geometry("1024x840")
        self.root.minsize(860, 720)
        self.root.configure(bg=C["bg"])
        self.root.resizable(True, True)

        # ── state ──
        self._session_active = False
        self._paused = False
        self._region: dict | None = None
        self._voice_enabled = tk.BooleanVar(value=True)
        self._show_overlay = tk.BooleanVar(value=True)
        self._fps_var = tk.DoubleVar(value=1.0)
        self._last_text = ""
        self._frame_count = 0
        self._session_start: float | None = None
        self._last_frame_time: float | None = None
        self._actual_fps: float = 0.0

        # pulse animation state
        self._pulse_step = 0
        self._pulse_colors = self._gen_pulse_colors(C["success"], 20)

        # ── modules ──
        self.capture = ScreenCapture(fps=1.0)
        self.ocr = OCRProcessor()
        self.analyzer = ContextAnalyzer()
        self.voice = VoiceFeedback()
        self.overlay = OverlayWindow(self.root)
        self.region_selector = RegionSelector(self.root)

        # ── build UI ──
        self._build_ui()
        self._apply_style()

        # ── keyboard shortcuts ──
        self.root.bind("<space>",   lambda e: self._kb_space())
        self.root.bind("<Escape>",  lambda e: self._stop_session())
        self.root.bind("<Control-r>", lambda e: self._select_region())
        self.root.bind("<Control-l>", lambda e: self._clear_ocr())

        # ── ticker ──
        self._tick()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════════════════════════════════
    #   UI construction
    # ═══════════════════════════════════════════════════════════════════

    def _build_ui(self):
        # ── header ──
        self._build_header()

        # ── main body (left | right) ──
        body = tk.Frame(self.root, bg=C["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 0))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        self._build_left(body)
        self._build_right(body)

        # ── log console (bottom) ──
        self._build_log_console()

        # ── status bar ──
        self._build_statusbar()

    # ── header ──────────────────────────────────────────────────────────

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=C["panel"], height=80)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        # Left: logo + title
        left = tk.Frame(hdr, bg=C["panel"])
        left.pack(side=tk.LEFT, padx=24, pady=16)

        # Animated dot canvas (pulse)
        self._dot_canvas = tk.Canvas(left, width=28, height=28,
                                     bg=C["panel"], highlightthickness=0)
        self._dot_canvas.pack(side=tk.LEFT, padx=(0, 12))
        self._dot_circle = self._dot_canvas.create_oval(4, 4, 24, 24,
                                                         fill=C["muted"], outline="")

        title_frame = tk.Frame(left, bg=C["panel"])
        title_frame.pack(side=tk.LEFT)

        title_row = tk.Frame(title_frame, bg=C["panel"])
        title_row.pack(anchor="w")

        tk.Label(title_row, text="BH-AI",
                 fg=C["text"], bg=C["panel"],
                 font=make_font(18, "bold")).pack(side=tk.LEFT)

        # DEV badge
        dev_badge = tk.Label(title_row, text=" DEV ",
                             fg=C["bg"], bg=C["dev"],
                             font=make_font(7, "bold"),
                             padx=4, pady=1)
        dev_badge.pack(side=tk.LEFT, padx=(10, 0), pady=(3, 0))

        tk.Label(title_frame, text="Privacy Assistant  ·  Debug Console Active",
                 fg=C["muted"], bg=C["panel"],
                 font=make_font(9)).pack(anchor="w")

        # Right: FPS meter + session timer + indicator
        right = tk.Frame(hdr, bg=C["panel"])
        right.pack(side=tk.RIGHT, padx=24)

        # FPS meter
        fps_block = tk.Frame(right, bg=C["panel"])
        fps_block.pack(side=tk.LEFT, padx=(0, 24))

        tk.Label(fps_block, text="ACTUAL FPS",
                 fg=C["muted"], bg=C["panel"],
                 font=make_font(7)).pack()
        self._fps_meter_lbl = tk.Label(fps_block, text="—",
                                        fg=C["accent"], bg=C["panel"],
                                        font=make_font(14, "bold"))
        self._fps_meter_lbl.pack()

        # Separator
        tk.Frame(right, bg=C["border"], width=1).pack(side=tk.LEFT,
                                                       fill=tk.Y, pady=12, padx=(0, 24))

        # Timer block
        timer_block = tk.Frame(right, bg=C["panel"])
        timer_block.pack(side=tk.LEFT)

        tk.Label(timer_block, text="SESSION TIME",
                 fg=C["muted"], bg=C["panel"],
                 font=make_font(7)).pack()
        self._timer_lbl = tk.Label(timer_block, text="00:00:00",
                                    fg=C["muted"], bg=C["panel"],
                                    font=make_font(14, "bold"))
        self._timer_lbl.pack()

        # Keyboard shortcut hints
        hints_frame = tk.Frame(hdr, bg=C["panel"])
        hints_frame.pack(side=tk.RIGHT, padx=(0, 20))
        for key, label in [("Space", "Pause"), ("Ctrl+R", "Region"),
                            ("Esc", "Stop"), ("Ctrl+L", "Clear")]:
            kb = tk.Frame(hints_frame, bg=C["dim"])
            kb.pack(side=tk.LEFT, padx=4)
            tk.Label(kb, text=key, fg=C["muted"], bg=C["dim"],
                     font=make_font(7), padx=6, pady=3).pack(side=tk.LEFT)
            tk.Label(kb, text=label, fg=C["text"], bg=C["dim"],
                     font=make_font(7), padx=6, pady=3).pack(side=tk.LEFT)

        # Separator line
        sep = tk.Frame(self.root, bg=C["border"], height=1)
        sep.pack(fill=tk.X)

    # ── left panel ──────────────────────────────────────────────────────

    def _build_left(self, parent):
        left = tk.Frame(parent, bg=C["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        # Controls card
        ctrl_outer = tk.Frame(left, bg=C["border"], pady=0)
        ctrl_outer.pack(fill=tk.X, pady=(16, 12))

        ctrl_header = tk.Frame(ctrl_outer, bg=C["panel"])
        ctrl_header.pack(fill=tk.X)
        tk.Label(ctrl_header, text="Session Controls", fg=C["accent"],
                 bg=C["panel"], font=make_font(10, "bold"),
                 anchor="w", padx=16, pady=10).pack(side=tk.LEFT, fill=tk.X)
        tk.Label(ctrl_header, text="Space=Pause  Ctrl+R=Region  Esc=Stop",
                 fg=C["dim"], bg=C["panel"],
                 font=make_font(8)).pack(side=tk.RIGHT, padx=16)
        tk.Frame(ctrl_outer, bg=C["border"], height=1).pack(fill=tk.X)

        ctrl_body = tk.Frame(ctrl_outer, bg=C["surface"], padx=16, pady=16)
        ctrl_body.pack(fill=tk.X)
        self._build_controls(ctrl_body)

        # Preview card
        prev_outer = tk.Frame(left, bg=C["border"])
        prev_outer.pack(fill=tk.BOTH, expand=True)

        prev_header = tk.Frame(prev_outer, bg=C["panel"])
        prev_header.pack(fill=tk.X)
        tk.Label(prev_header, text="Live Preview", fg=C["accent"],
                 bg=C["panel"], font=make_font(10, "bold"),
                 anchor="w", padx=16, pady=10).pack(side=tk.LEFT, fill=tk.X)

        self._frame_count_lbl = tk.Label(prev_header, text="0 frames",
                                          fg=C["muted"], bg=C["panel"],
                                          font=make_font(9))
        self._frame_count_lbl.pack(side=tk.RIGHT, padx=16)

        tk.Frame(prev_outer, bg=C["border"], height=1).pack(fill=tk.X)

        prev_body = tk.Frame(prev_outer, bg=C["surface"], padx=0, pady=0)
        prev_body.pack(fill=tk.BOTH, expand=True)
        self._build_preview(prev_body)

    def _build_controls(self, parent):
        row1 = tk.Frame(parent, bg=C["surface"])
        row1.pack(fill=tk.X, pady=(0, 16))

        self._btn_start = RoundedButton(
            row1, text="▶  Start Session", bg_color=C["success"], fg_color=C["bg"],
            command=self._start_session, width=150, height=34
        )
        self._btn_start.pack(side=tk.LEFT, padx=(0, 12))

        self._btn_pause = RoundedButton(
            row1, text="⏸  Pause", bg_color=C["warning"], fg_color=C["bg"],
            command=self._pause_session, state=tk.DISABLED, width=100, height=34
        )
        self._btn_pause.pack(side=tk.LEFT, padx=(0, 12))

        self._btn_stop = RoundedButton(
            row1, text="⏹  Stop", bg_color=C["danger"], fg_color=C["bg"],
            command=self._stop_session, state=tk.DISABLED, width=100, height=34
        )
        self._btn_stop.pack(side=tk.LEFT)

        row2 = tk.Frame(parent, bg=C["surface"])
        row2.pack(fill=tk.X, pady=(8, 0))

        self._btn_region = RoundedButton(
            row2, text="⊡  Select Region", bg_color=C["accent"], fg_color=C["bg"],
            command=self._select_region, width=140, height=34
        )
        self._btn_region.pack(side=tk.LEFT, padx=(0, 16))

        self._region_lbl = tk.Label(row2,
                                     text="No region selected",
                                     fg=C["muted"], bg=C["surface"],
                                     font=make_font(9))
        self._region_lbl.pack(side=tk.LEFT, pady=6)

        # Options row
        row3 = tk.Frame(parent, bg=C["surface"])
        row3.pack(fill=tk.X, pady=(16, 0))

        self._chk_voice = tk.Checkbutton(
            row3, text="Voice feedback",
            variable=self._voice_enabled,
            fg=C["text"], bg=C["surface"],
            selectcolor=C["panel"],
            activebackground=C["surface"],
            activeforeground=C["accent"],
            font=make_font(9),
            command=self._toggle_voice,
        )
        self._chk_voice.pack(side=tk.LEFT, padx=(0, 20))

        self._chk_overlay = tk.Checkbutton(
            row3, text="Show overlay",
            variable=self._show_overlay,
            fg=C["text"], bg=C["surface"],
            selectcolor=C["panel"],
            activebackground=C["surface"],
            activeforeground=C["accent"],
            font=make_font(9),
            command=self._toggle_overlay,
        )
        self._chk_overlay.pack(side=tk.LEFT, padx=(0, 20))

        # FPS slider
        tk.Label(row3, text="FPS:", fg=C["muted"], bg=C["surface"],
                 font=make_font(9)).pack(side=tk.LEFT)

        fps_slider = ttk.Scale(
            row3, from_=0.2, to=5.0, orient=tk.HORIZONTAL,
            variable=self._fps_var, length=120,
            command=self._fps_changed,
        )
        fps_slider.pack(side=tk.LEFT, padx=10)

        self._fps_lbl = tk.Label(row3, text="1.0", fg=C["accent"],
                                  bg=C["surface"], font=make_font(9, "bold"),
                                  width=3)
        self._fps_lbl.pack(side=tk.LEFT)

    def _build_preview(self, parent):
        self._preview_canvas = tk.Canvas(
            parent,
            bg=C["panel"],
            highlightthickness=0,
            cursor="crosshair",
        )
        self._preview_canvas.pack(fill=tk.BOTH, expand=True)
        self._preview_canvas.bind("<Configure>", self._resize_preview)

        self._no_preview_text = self._preview_canvas.create_text(
            300, 200,
            text="No capture active\n\nSelect a region and start the session",
            fill=C["muted"],
            font=make_font(12),
            justify=tk.CENTER,
        )
        self._preview_image_id = None
        self._preview_photo = None

    # ── right panel ─────────────────────────────────────────────────────

    def _build_right(self, parent):
        right = tk.Frame(parent, bg=C["bg"])
        right.grid(row=0, column=1, sticky="nsew")

        # Insights card
        ins_outer = tk.Frame(right, bg=C["border"])
        ins_outer.pack(fill=tk.BOTH, expand=True, pady=(16, 12))

        ins_header = tk.Frame(ins_outer, bg=C["panel"])
        ins_header.pack(fill=tk.X)
        tk.Label(ins_header, text="Context Insights", fg=C["accent"],
                 bg=C["panel"], font=make_font(10, "bold"),
                 anchor="w", padx=16, pady=10).pack(fill=tk.X)
        tk.Frame(ins_outer, bg=C["border"], height=1).pack(fill=tk.X)

        ins_body = tk.Frame(ins_outer, bg=C["surface"], padx=16, pady=16)
        ins_body.pack(fill=tk.BOTH, expand=True)
        self._build_insights(ins_body)

        # OCR output card
        ocr_outer = tk.Frame(right, bg=C["border"])
        ocr_outer.pack(fill=tk.BOTH, expand=True)

        ocr_header = tk.Frame(ocr_outer, bg=C["panel"])
        ocr_header.pack(fill=tk.X)
        tk.Label(ocr_header, text="OCR Output", fg=C["accent"],
                 bg=C["panel"], font=make_font(10, "bold"),
                 anchor="w", padx=16, pady=10).pack(side=tk.LEFT, fill=tk.X)
        
        clear_btn = RoundedButton(
            ocr_header, text="Clear", bg_color=C["surface"], fg_color=C["text"],
            command=self._clear_ocr, hover_color=C["danger"], width=70, height=28,
            font=make_font(8)
        )
        clear_btn.pack(side=tk.RIGHT, padx=16, pady=6)
        
        tk.Frame(ocr_outer, bg=C["border"], height=1).pack(fill=tk.X)

        ocr_body = tk.Frame(ocr_outer, bg=C["surface"], padx=16, pady=16)
        ocr_body.pack(fill=tk.BOTH, expand=True)
        self._build_ocr_output(ocr_body)

    def _build_insights(self, parent):
        self._insights_frame = tk.Frame(parent, bg=C["surface"])
        self._insights_frame.pack(fill=tk.BOTH, expand=True)
        self._show_no_insights()

    def _show_no_insights(self):
        for w in self._insights_frame.winfo_children():
            w.destroy()

        tk.Label(
            self._insights_frame,
            text="Insights will appear here\nonce the session is active.",
            fg=C["muted"], bg=C["surface"],
            font=make_font(11),
            justify=tk.CENTER,
        ).pack(expand=True)

    def _update_insights(self, insights: list[Insight]):
        for w in self._insights_frame.winfo_children():
            w.destroy()

        if not insights:
            self._show_no_insights()
            return

        for ins in insights:
            row = tk.Frame(self._insights_frame, bg=C["panel"], relief="flat")
            row.pack(fill=tk.X, pady=4, padx=0)

            hint_colors = {
                "top": C["danger"], "form": C["warning"],
                "search": C["accent"], "password": C["danger"], "": C["success"],
            }
            color = hint_colors.get(ins.highlight_hint, C["accent"])
            tk.Frame(row, bg=color, width=6).pack(side=tk.LEFT, fill=tk.Y)

            content = tk.Frame(row, bg=C["panel"])
            content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=10)

            top = tk.Frame(content, bg=C["panel"])
            top.pack(fill=tk.X)

            tk.Label(top, text=ins.label, fg=C["text"], bg=C["panel"],
                     font=make_font(11, "bold")).pack(side=tk.LEFT)

            pct = int(ins.confidence * 100)
            pct_color = C["success"] if pct >= 60 else C["warning"] if pct >= 30 else C["danger"]
            tk.Label(top, text=f"{pct}%", fg=pct_color, bg=C["panel"],
                     font=make_font(10, "bold")).pack(side=tk.RIGHT)

            kw_text = "  ".join(f"#{k}" for k in ins.keywords[:5])
            tk.Label(content, text=kw_text, fg=C["accent"], bg=C["panel"],
                     font=make_font(9), wraplength=280, justify=tk.LEFT
                     ).pack(fill=tk.X, pady=(4, 6))

            tk.Label(content, text=ins.suggestion, fg=C["muted"],
                     bg=C["panel"], font=make_font(9),
                     wraplength=280, justify=tk.LEFT).pack(fill=tk.X)

    def _build_ocr_output(self, parent):
        self._ocr_text = scrolledtext.ScrolledText(
            parent,
            bg=C["panel"],
            fg=C["text"],
            insertbackground=C["accent"],
            font=("Consolas", 10),
            wrap=tk.WORD,
            relief="flat",
            state=tk.DISABLED,
            height=10,
        )
        self._ocr_text.pack(fill=tk.BOTH, expand=True)

    # ── log console ──────────────────────────────────────────────────────

    def _build_log_console(self):
        log_outer = tk.Frame(self.root, bg=C["border"])
        log_outer.pack(fill=tk.X, padx=20, pady=(0, 12))

        log_header = tk.Frame(log_outer, bg=C["panel"])
        log_header.pack(fill=tk.X)

        tk.Label(log_header, text="▼  Debug Log", fg=C["dev"],
                 bg=C["panel"], font=make_font(9, "bold"),
                 anchor="w", padx=16, pady=8).pack(side=tk.LEFT)

        tk.Label(log_header, text="Internal diagnostics — frame timing, OCR, analysis events",
                 fg=C["muted"], bg=C["panel"],
                 font=make_font(8)).pack(side=tk.LEFT, padx=12)

        clear_log = RoundedButton(
            log_header, text="Clear Log", bg_color=C["surface"], fg_color=C["text"],
            command=self._clear_log, hover_color=C["dev"], width=80, height=26,
            font=make_font(8)
        )
        clear_log.pack(side=tk.RIGHT, padx=16, pady=4)

        tk.Frame(log_outer, bg=C["border"], height=1).pack(fill=tk.X)

        self._log_text = tk.Text(
            log_outer,
            bg=C["panel"],
            fg=C["muted"],
            insertbackground=C["accent"],
            font=("Consolas", 9),
            wrap=tk.WORD,
            relief="flat",
            state=tk.DISABLED,
            height=6,
        )
        self._log_text.pack(fill=tk.X)

        # Configure tag colors
        self._log_text.tag_configure("INFO",    foreground=C["text"])
        self._log_text.tag_configure("OK",      foreground=C["success"])
        self._log_text.tag_configure("WARN",    foreground=C["warning"])
        self._log_text.tag_configure("ERR",     foreground=C["danger"])
        self._log_text.tag_configure("DEV",     foreground=C["dev"])
        self._log_text.tag_configure("ts",      foreground=C["dim"])

        self._log("Dev Mode initialized", "DEV")
        self._log(f"OCR: {'available' if self.ocr.available else 'NOT available'}", "OK" if self.ocr.available else "ERR")
        self._log(f"TTS: {'available' if self.voice.available else 'not available'}", "OK" if self.voice.available else "WARN")

    # ── status bar ──────────────────────────────────────────────────────

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=C["panel"], height=32)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar.pack_propagate(False)

        self._status_lbl = tk.Label(
            bar,
            text="Ready  ·  Select a region and press Start  ·  Keyboard: Space=Pause  Esc=Stop",
            fg=C["muted"], bg=C["panel"],
            font=make_font(9),
            anchor="w",
        )
        self._status_lbl.pack(side=tk.LEFT, padx=16, pady=6)

        ocr_txt = "OCR ✓" if self.ocr.available else "OCR ✗ (install Tesseract)"
        ocr_color = C["success"] if self.ocr.available else C["danger"]
        tk.Label(bar, text=ocr_txt, fg=ocr_color, bg=C["panel"],
                 font=make_font(9)).pack(side=tk.RIGHT, padx=16)

        tts_txt = "TTS ✓" if self.voice.available else "TTS ✗"
        tts_color = C["success"] if self.voice.available else C["muted"]
        tk.Label(bar, text=tts_txt, fg=tts_color, bg=C["panel"],
                 font=make_font(9)).pack(side=tk.RIGHT, padx=8)

    # ═══════════════════════════════════════════════════════════════════
    #   Helpers
    # ═══════════════════════════════════════════════════════════════════

    def _apply_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Horizontal.TScale",
            background=C["surface"],
            troughcolor=C["border"],
            sliderlength=16,
        )

    @staticmethod
    def _gen_pulse_colors(base: str, steps: int) -> list[str]:
        try:
            r = int(base[1:3], 16)
            g = int(base[3:5], 16)
            b = int(base[5:7], 16)
            colors = []
            for i in range(steps):
                t = (i / (steps - 1))
                factor = (1 - abs(2 * t - 1)) ** 0.5
                nr = int(r * factor * 0.9 + 40)
                ng = int(g * factor * 0.9 + 40)
                nb = int(b * factor * 0.9 + 40)
                colors.append(f"#{min(nr,255):02x}{min(ng,255):02x}{min(nb,255):02x}")
            return colors
        except Exception:
            return [base] * steps

    # ═══════════════════════════════════════════════════════════════════
    #   Event handlers
    # ═══════════════════════════════════════════════════════════════════

    def _kb_space(self):
        if self._session_active:
            self._pause_session()

    def _select_region(self):
        self._set_status("Click and drag to select a screen region…")
        self._log("Opening region selector…", "INFO")
        self.root.after(200, self._do_select_region)

    def _do_select_region(self):
        sel = self.region_selector.select()
        if sel:
            self._region = sel
            self._region_lbl.config(
                text=f"x={sel['left']}  y={sel['top']}  "
                     f"{sel['width']}×{sel['height']} px",
                fg=C["accent"],
            )
            self.capture.set_region(sel["left"], sel["top"], sel["width"], sel["height"])
            self._set_status("Region selected. Press Start to begin session.")
            self._log(f"Region set: x={sel['left']} y={sel['top']} {sel['width']}×{sel['height']}px", "OK")
        else:
            self._set_status("Region selection cancelled.")
            self._log("Region selection cancelled.", "WARN")

    def _start_session(self):
        if self._region is None:
            self._set_status("⚠  Please select a screen region first.", C["warning"])
            self._log("Start failed — no region selected.", "WARN")
            return

        if self._paused:
            self._paused = False
            self.capture.resume()
            if self._show_overlay.get():
                self.overlay.show()
            self._update_session_buttons(running=True, paused=False)
            self._set_status("Session resumed.", C["success"])
            self._log("Session resumed.", "OK")
            return

        self._session_active = True
        self._paused = False
        self._frame_count = 0
        self._session_start = time.time()
        self._last_frame_time = None
        self._pulse_step = 0

        self.capture.set_callback(self._on_frame)
        self.capture.fps = self._fps_var.get()
        self.capture.start()

        if self._show_overlay.get():
            self.overlay.show()

        self._update_session_buttons(running=True, paused=False)
        self._set_status("Session active — monitoring screen…", C["success"])
        self._log(f"Session started @ {self._fps_var.get():.1f} FPS", "OK")

        if self.voice.available and self._voice_enabled.get():
            self.voice.speak("Privacy assistant session started.")

    def _pause_session(self):
        if not self._session_active:
            return

        if self._paused:
            self._start_session()
            return

        self._paused = True
        self.capture.pause()
        self.overlay.hide()

        self._update_session_buttons(running=True, paused=True)
        self._set_status("Session paused. Screen capture stopped.", C["warning"])
        self._log("Session paused.", "WARN")
        self._fps_meter_lbl.config(text="—")

    def _stop_session(self):
        if not self._session_active and not self._paused:
            return

        was_active = self._session_active
        self._session_active = False
        self._paused = False
        self._session_start = None

        self.capture.stop()
        self.overlay.clear()
        self.overlay.hide()

        self._update_session_buttons(running=False, paused=False)
        self._set_status("Session stopped.")
        self._timer_lbl.config(text="00:00:00", fg=C["muted"])
        self._fps_meter_lbl.config(text="—")
        self._dot_canvas.itemconfig(self._dot_circle, fill=C["muted"])

        self._preview_canvas.delete("all")
        self._no_preview_text = self._preview_canvas.create_text(
            self._preview_canvas.winfo_width() // 2 or 300,
            self._preview_canvas.winfo_height() // 2 or 200,
            text="No capture active\n\nSelect a region and start the session",
            fill=C["muted"], font=make_font(12), justify=tk.CENTER,
        )
        self._show_no_insights()

        if was_active:
            self._log("Session stopped.", "INFO")

    def _update_session_buttons(self, running: bool, paused: bool):
        if not running:
            self._btn_start.config_state(tk.NORMAL)
            self._btn_start.config_text("▶  Start Session")
            self._btn_pause.config_state(tk.DISABLED)
            self._btn_pause.config_text("⏸  Pause")
            self._btn_stop.config_state(tk.DISABLED)
        elif paused:
            self._btn_start.config_state(tk.NORMAL)
            self._btn_start.config_text("▶  Resume")
            self._btn_pause.config_state(tk.NORMAL)
            self._btn_pause.config_text("⏸  Paused")
            self._btn_stop.config_state(tk.NORMAL)
        else:
            self._btn_start.config_state(tk.DISABLED)
            self._btn_start.config_text("▶  Running…")
            self._btn_pause.config_state(tk.NORMAL)
            self._btn_pause.config_text("⏸  Pause")
            self._btn_stop.config_state(tk.NORMAL)

    def _toggle_voice(self):
        self.voice.set_enabled(self._voice_enabled.get())
        self._log(f"Voice feedback {'on' if self._voice_enabled.get() else 'off'}.", "INFO")

    def _toggle_overlay(self):
        if self._show_overlay.get() and self._session_active and not self._paused:
            self.overlay.show()
        else:
            self.overlay.hide()
        self._log(f"Overlay {'shown' if self._show_overlay.get() else 'hidden'}.", "INFO")

    def _fps_changed(self, _=None):
        fps = round(self._fps_var.get(), 1)
        self._fps_lbl.config(text=str(fps))
        self.capture.fps = fps

    def _clear_ocr(self):
        self._ocr_text.config(state=tk.NORMAL)
        self._ocr_text.delete("1.0", tk.END)
        self._ocr_text.config(state=tk.DISABLED)
        self._log("OCR output cleared.", "INFO")

    def _clear_log(self):
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state=tk.DISABLED)

    def _log(self, msg: str, level: str = "INFO"):
        try:
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self._log_text.config(state=tk.NORMAL)
            self._log_text.insert(tk.END, f"[{ts}] ", "ts")
            self._log_text.insert(tk.END, f"[{level}] ", level)
            self._log_text.insert(tk.END, f"{msg}\n", "INFO")
            self._log_text.see(tk.END)
            self._log_text.config(state=tk.DISABLED)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════
    #   Frame processing pipeline
    # ═══════════════════════════════════════════════════════════════════

    def _on_frame(self, image: Image.Image):
        t0 = time.time()
        text = self.ocr.extract_text(image)
        insights = self.analyzer.analyze(text)
        ocr_time = time.time() - t0
        self.root.after(0, lambda: self._update_ui(image, text, insights, ocr_time))

    def _update_ui(self, image: Image.Image, text: str, insights: list[Insight],
                   ocr_time: float = 0.0):
        now = time.time()
        if self._last_frame_time:
            delta = now - self._last_frame_time
            self._actual_fps = round(1.0 / delta, 1) if delta > 0 else 0.0
            self._fps_meter_lbl.config(text=f"{self._actual_fps:.1f}")
        self._last_frame_time = now

        self._frame_count += 1
        self._frame_count_lbl.config(text=f"{self._frame_count} frames")

        self._render_preview(image)

        if text != self._last_text and text:
            self._last_text = text
            self._append_ocr(text)
            self._log(f"OCR extracted {len(text)} chars in {ocr_time*1000:.0f}ms  |  {len(insights)} insight(s)", "DEV")

            if insights and self._voice_enabled.get():
                summary = self.analyzer.summarize(insights)
                self.voice.speak(summary)

        self._update_insights(insights)

        if self._show_overlay.get() and self._region:
            hint = insights[0].highlight_hint if insights else ""
            rect = self.overlay.build_region_rect(self._region, hint)
            self.overlay.set_rects([rect])

    def _render_preview(self, image: Image.Image):
        cw = self._preview_canvas.winfo_width()
        ch = self._preview_canvas.winfo_height()
        if cw < 2 or ch < 2:
            return

        img_copy = image.copy()
        img_copy.thumbnail((cw, ch), Image.LANCZOS)
        self._preview_photo = ImageTk.PhotoImage(img_copy)

        self._preview_canvas.delete("all")
        self._preview_canvas.create_image(
            cw // 2, ch // 2,
            anchor=tk.CENTER,
            image=self._preview_photo,
        )

    def _append_ocr(self, text: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._ocr_text.config(state=tk.NORMAL)
        self._ocr_text.insert(tk.END, f"\n── {ts} ──\n{text}\n")
        self._ocr_text.see(tk.END)
        self._ocr_text.config(state=tk.DISABLED)

    # ═══════════════════════════════════════════════════════════════════
    #   Ticker — session timer + animated dot
    # ═══════════════════════════════════════════════════════════════════

    def _tick(self):
        if self._session_active and not self._paused and self._session_start:
            elapsed = int(time.time() - self._session_start)
            h = elapsed // 3600
            m = (elapsed % 3600) // 60
            s = elapsed % 60
            self._timer_lbl.config(
                text=f"{h:02d}:{m:02d}:{s:02d}",
                fg=C["success"],
            )
            # Pulsing dot animation
            color = self._pulse_colors[self._pulse_step % len(self._pulse_colors)]
            self._dot_canvas.itemconfig(self._dot_circle, fill=color)
            self._pulse_step += 1

        elif self._paused:
            self._dot_canvas.itemconfig(self._dot_circle, fill=C["warning"])

        self.root.after(100, self._tick)

    # ═══════════════════════════════════════════════════════════════════
    #   Misc
    # ═══════════════════════════════════════════════════════════════════

    def _resize_preview(self, event):
        if not self._session_active:
            self._preview_canvas.delete("all")
            self._preview_canvas.create_text(
                event.width // 2, event.height // 2,
                text="No capture active\n\nSelect a region and start the session",
                fill=C["muted"], font=make_font(12), justify=tk.CENTER,
            )

    def _set_status(self, msg: str, color: str = None):
        self._status_lbl.config(
            text=msg,
            fg=color or C["muted"],
        )

    def _on_close(self):
        self.capture.stop()
        self.voice.stop()
        self.overlay.hide()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
