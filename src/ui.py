"""
Privacy-Focused Desktop Assistant — Dev Mode UI
A clean, minimal, non-purple graphite control panel.
"""

import math
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
from src.privacy import PIIRedactor, WindowBlocklistMonitor, get_foreground_window_info
from src.memory import MemoryDatabase, EmbeddingEngine, EpisodicRAGEngine
from src.reasoning import LocalLLMDriver, LLMBackend
from src.voice import VoiceTriggerController
from src.region_selector import RegionSelector

from src.ui_theme import (
    ctk, C, SPACING, LOG_ICONS,
    make_font, make_mono, make_card, make_card_header, make_separator,
    gen_sine_pulse, lerp_color, style_scale_dark,
)

SP = SPACING  # shorthand


class AssistantUI:

    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("BH-AI  ·  Control Suite")
        self.root.geometry("1080x860")
        self.root.minsize(920, 720)
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

        # Smooth sine pulse tables
        self._pulse_step = 0
        self._pulse_colors = gen_sine_pulse(C["success"], C["surface"], 32)

        # ── modules ──
        self.capture = ScreenCapture(fps=1.0)
        self.ocr = OCRProcessor()
        self.analyzer = ContextAnalyzer()
        self.voice = VoiceFeedback()
        self.overlay = OverlayWindow(self.root)
        self.pii = PIIRedactor()
        self.db = MemoryDatabase()
        self.embeddings = EmbeddingEngine(dimension=64)
        self.rag = EpisodicRAGEngine(db=self.db, embeddings=self.embeddings)
        self.llm = LocalLLMDriver(backend=LLMBackend.AUTO)
        self.blocklist_monitor = WindowBlocklistMonitor(state_machine=self.capture.state_machine)
        self.trigger_controller = VoiceTriggerController(
            state_machine=self.capture.state_machine,
            on_trigger=self._on_voice_or_ptt_trigger if hasattr(self, '_on_voice_or_ptt_trigger') else lambda x: None,
        )
        self._current_session_id = None
        self._is_llm_streaming = False
        import queue
        self._llm_queue = queue.Queue()
        self.region_selector = RegionSelector(self.root)

        # ── build UI ──
        self._build_ui()
        self._apply_style()

        # ── shortcuts ──
        self.root.bind("<space>", lambda e: self._kb_space())
        self.root.bind("<Escape>", lambda e: self._stop_session())
        self.root.bind("<Control-r>", lambda e: self._select_region())
        self.root.bind("<Control-l>", lambda e: self._clear_ocr())

        # ── ticker ──
        self._tick()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════════════════════════════════
    #   UI construction
    # ═══════════════════════════════════════════════════════════════════

    def _build_ui(self):
        self._build_header()

        body = ctk.CTkFrame(self.root, fg_color=C["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=SP["xl"], pady=(SP["lg"], 0))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        self._build_left(body)
        self._build_right(body)

        self._build_log_console()
        self._build_statusbar()

    def _build_header(self):
        hdr = ctk.CTkFrame(self.root, fg_color=C["surface"], height=64, corner_radius=0)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        # Left Branding
        left = ctk.CTkFrame(hdr, fg_color=C["surface"])
        left.pack(side=tk.LEFT, padx=20, pady=SP["md"])

        self._dot_canvas = tk.Canvas(left, width=22, height=22, bg=C["surface"], highlightthickness=0)
        self._dot_canvas.pack(side=tk.LEFT, padx=(0, SP["md"]))
        # Outer glow ring
        self._dot_glow = self._dot_canvas.create_oval(1, 1, 21, 21, fill="", outline=C["dim"], width=2)
        self._dot_circle = self._dot_canvas.create_oval(5, 5, 17, 17, fill=C["dim"], outline="")

        title_frame = ctk.CTkFrame(left, fg_color=C["surface"])
        title_frame.pack(side=tk.LEFT)

        title_row = ctk.CTkFrame(title_frame, fg_color=C["surface"])
        title_row.pack(anchor="w")

        ctk.CTkLabel(title_row, text="BH-AI", text_color=C["text"], fg_color=C["surface"],
                     font=make_font(15, "bold")).pack(side=tk.LEFT)

        dev_badge = ctk.CTkLabel(title_row, text=" DEV ", text_color=C["bg"], fg_color=C["dev"],
                                 corner_radius=4, font=make_font(8, "bold"), padx=5, pady=1)
        dev_badge.pack(side=tk.LEFT, padx=(SP["sm"], 0))

        ctk.CTkLabel(title_frame, text="Privacy Sentinel & Context Stream",
                     text_color=C["muted"], fg_color=C["surface"], font=make_font(9)).pack(anchor="w")

        # Right Telemetry
        right = ctk.CTkFrame(hdr, fg_color=C["surface"])
        right.pack(side=tk.RIGHT, padx=20)

        # Metrics
        fps_block = ctk.CTkFrame(right, fg_color=C["surface"])
        fps_block.pack(side=tk.LEFT, padx=(0, 20))
        ctk.CTkLabel(fps_block, text="CAPTURE FPS", text_color=C["dim"], fg_color=C["surface"],
                     font=make_font(8, "bold")).pack()
        self._fps_meter_lbl = ctk.CTkLabel(fps_block, text="0.0", text_color=C["accent"],
                                           fg_color=C["surface"], font=make_font(13, "bold"))
        self._fps_meter_lbl.pack()

        ctk.CTkFrame(right, fg_color=C["border"], width=1, height=28).pack(side=tk.LEFT, padx=(0, 20))

        timer_block = ctk.CTkFrame(right, fg_color=C["surface"])
        timer_block.pack(side=tk.LEFT, padx=(0, SP["lg"]))
        ctk.CTkLabel(timer_block, text="ELAPSED", text_color=C["dim"], fg_color=C["surface"],
                     font=make_font(8, "bold")).pack()
        self._timer_lbl = ctk.CTkLabel(timer_block, text="00:00:00", text_color=C["muted"],
                                       fg_color=C["surface"], font=make_font(13, "bold"))
        self._timer_lbl.pack()

        # Keyboard shortcut hints
        hints_frame = ctk.CTkFrame(hdr, fg_color=C["surface"])
        hints_frame.pack(side=tk.RIGHT, padx=(0, SP["lg"]))
        for key, label in [("Space", "Pause"), ("Ctrl+R", "Region"), ("Esc", "Stop")]:
            kb = ctk.CTkFrame(hints_frame, fg_color=C["panel"], corner_radius=4)
            kb.pack(side=tk.LEFT, padx=3)
            ctk.CTkLabel(kb, text=key, text_color=C["muted"], fg_color=C["panel"],
                         font=make_font(8, "bold"), padx=5, pady=2).pack(side=tk.LEFT)
            ctk.CTkLabel(kb, text=label, text_color=C["dim"], fg_color=C["panel"],
                         font=make_font(8), padx=5, pady=2).pack(side=tk.LEFT)

        # Header bottom accent line (gradient effect via 2 thin frames)
        accent_line = ctk.CTkFrame(self.root, fg_color=C["border"], height=1)
        accent_line.pack(fill=tk.X)

    def _build_left(self, parent):
        left = ctk.CTkFrame(parent, fg_color=C["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, SP["md"]))

        # Controls Card
        ctrl_card = make_card(left)
        ctrl_card.pack(fill=tk.X, pady=(0, SP["lg"] - 2))

        ctrl_header = make_card_header(ctrl_card, "Execution Controls", icon="▸")
        ctrl_body = ctk.CTkFrame(ctrl_card, fg_color=C["surface"])
        ctrl_body.pack(fill=tk.X, padx=SP["lg"], pady=(0, SP["md"]))
        self._build_controls(ctrl_body)

        # Preview Card
        prev_card = make_card(left)
        prev_card.pack(fill=tk.BOTH, expand=True)

        prev_header = make_card_header(prev_card, "Active Viewport", icon="◉")
        self._frame_count_lbl = ctk.CTkLabel(prev_header, text="0 frames",
                                             text_color=C["muted"], fg_color=C["surface"], font=make_font(9))
        self._frame_count_lbl.pack(side=tk.RIGHT)

        prev_body = ctk.CTkFrame(prev_card, fg_color=C["panel"], corner_radius=6)
        prev_body.pack(fill=tk.BOTH, expand=True, padx=SP["md"], pady=(0, SP["md"]))
        self._build_preview(prev_body)

    def _build_controls(self, parent):
        row1 = ctk.CTkFrame(parent, fg_color=C["surface"])
        row1.pack(fill=tk.X, pady=(0, SP["sm"] + 2))

        self._btn_start = ctk.CTkButton(
            row1, text="▶  Start", fg_color=C["accent"], hover_color=C["accent_hov"],
            text_color=C["bg"], corner_radius=6, command=self._start_session, width=110, height=32,
            font=make_font(9, "bold")
        )
        self._btn_start.pack(side=tk.LEFT, padx=(0, SP["sm"]))

        self._btn_pause = ctk.CTkButton(
            row1, text="⏸  Pause", fg_color=C["panel_alt"], hover_color=C["border_focus"],
            text_color=C["text"], corner_radius=6, command=self._pause_session,
            state="disabled", width=90, height=32, font=make_font(9)
        )
        self._btn_pause.pack(side=tk.LEFT, padx=(0, SP["sm"]))

        self._btn_stop = ctk.CTkButton(
            row1, text="⏹  Stop", fg_color=C["panel_alt"], hover_color=C["danger"],
            text_color=C["text"], corner_radius=6, command=self._stop_session,
            state="disabled", width=90, height=32, font=make_font(9)
        )
        self._btn_stop.pack(side=tk.LEFT)

        row2 = ctk.CTkFrame(parent, fg_color=C["surface"])
        row2.pack(fill=tk.X, pady=(0, SP["sm"] + 2))

        self._btn_region = ctk.CTkButton(
            row2, text="⬡  Select Region", fg_color=C["panel_alt"], hover_color=C["border_focus"],
            text_color=C["text"], corner_radius=6, command=self._select_region, width=130, height=30,
            font=make_font(9)
        )
        self._btn_region.pack(side=tk.LEFT, padx=(0, SP["md"]))

        self._region_lbl = ctk.CTkLabel(row2, text="No target bounding-box defined",
                                        text_color=C["muted"], fg_color=C["surface"], font=make_font(9))
        self._region_lbl.pack(side=tk.LEFT)

        # Options
        row3 = ctk.CTkFrame(parent, fg_color=C["surface"])
        row3.pack(fill=tk.X)

        self._chk_voice = ctk.CTkCheckBox(
            row3, text="Voice synthesis", variable=self._voice_enabled,
            text_color=C["text"], fg_color=C["accent"], font=make_font(9),
            command=self._toggle_voice
        )
        self._chk_voice.pack(side=tk.LEFT, padx=(0, SP["lg"]))

        self._chk_overlay = ctk.CTkCheckBox(
            row3, text="Display overlay", variable=self._show_overlay,
            text_color=C["text"], fg_color=C["accent"], font=make_font(9),
            command=self._toggle_overlay
        )
        self._chk_overlay.pack(side=tk.LEFT, padx=(0, 20))

        ctk.CTkLabel(row3, text="Polling FPS:", text_color=C["muted"], fg_color=C["surface"],
                     font=make_font(9)).pack(side=tk.LEFT)

        fps_slider = ttk.Scale(
            row3, from_=0.2, to=5.0, orient=tk.HORIZONTAL,
            variable=self._fps_var, length=100, command=self._fps_changed
        )
        fps_slider.pack(side=tk.LEFT, padx=SP["sm"])

        self._fps_lbl = ctk.CTkLabel(row3, text="1.0", text_color=C["accent"],
                                     fg_color=C["surface"], font=make_font(9, "bold"), width=30)
        self._fps_lbl.pack(side=tk.LEFT)

    def _build_preview(self, parent):
        self._preview_canvas = tk.Canvas(parent, bg=C["panel"], highlightthickness=0, cursor="crosshair")
        self._preview_canvas.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self._preview_canvas.bind("<Configure>", self._resize_preview)

        self._draw_idle_preview()
        self._preview_image_id = None
        self._preview_photo = None

    def _draw_idle_preview(self, width=None, height=None):
        """Draw a subtle crosshatch grid pattern with centered idle text."""
        c = self._preview_canvas
        c.delete("all")
        w = width or c.winfo_width() or 520
        h = height or c.winfo_height() or 360

        # Draw subtle grid
        grid_spacing = 40
        for x in range(0, w, grid_spacing):
            c.create_line(x, 0, x, h, fill=C["border"], width=1, dash=(2, 6))
        for y in range(0, h, grid_spacing):
            c.create_line(0, y, w, y, fill=C["border"], width=1, dash=(2, 6))

        # Center icon and text
        cx, cy = w // 2, h // 2
        c.create_text(cx, cy - 16, text="⬡", fill=C["dim"], font=make_font(24))
        c.create_text(
            cx, cy + 20,
            text="Select bounding region to begin capture",
            fill=C["dim"], font=make_font(10), justify=tk.CENTER
        )

    def _build_right(self, parent):
        right = ctk.CTkFrame(parent, fg_color=C["bg"])
        right.grid(row=0, column=1, sticky="nsew")

        # Insights Card
        ins_card = make_card(right)
        ins_card.pack(fill=tk.BOTH, expand=True, pady=(0, SP["lg"] - 2))

        make_card_header(ins_card, "Context Synthesizer", icon="◈")

        ins_body = ctk.CTkFrame(ins_card, fg_color=C["surface"])
        ins_body.pack(fill=tk.BOTH, expand=True, padx=SP["md"], pady=(0, SP["md"]))
        self._build_insights(ins_body)

        # OCR Output Card
        ocr_card = make_card(right)
        ocr_card.pack(fill=tk.BOTH, expand=True)

        ocr_header = make_card_header(ocr_card, "OCR Buffer (PII Scrubbed)", icon="▤")

        clear_btn = ctk.CTkButton(
            ocr_header, text="Clear", fg_color=C["panel"], text_color=C["muted"],
            hover_color=C["danger"], corner_radius=4, command=self._clear_ocr, width=54, height=24,
            font=make_font(8)
        )
        clear_btn.pack(side=tk.RIGHT)

        ocr_body = ctk.CTkFrame(ocr_card, fg_color=C["surface"])
        ocr_body.pack(fill=tk.BOTH, expand=True, padx=SP["md"], pady=(0, SP["md"]))
        self._build_ocr_output(ocr_body)

    def _build_insights(self, parent):
        self._insights_frame = ctk.CTkFrame(parent, fg_color=C["surface"])
        self._insights_frame.pack(fill=tk.BOTH, expand=True)
        self._show_no_insights()

    def _show_no_insights(self):
        for w in self._insights_frame.winfo_children():
            w.destroy()

        no_data = ctk.CTkFrame(self._insights_frame, fg_color=C["surface"])
        no_data.pack(expand=True)
        ctk.CTkLabel(no_data, text="◇", text_color=C["dim"], fg_color=C["surface"],
                     font=make_font(20)).pack(pady=(0, SP["xs"]))
        ctk.CTkLabel(
            no_data, text="Awaiting active stream input\nNo inferences generated",
            text_color=C["dim"], fg_color=C["surface"], font=make_font(10), justify=tk.CENTER
        ).pack()

    def _update_insights(self, insights: list[Insight]):
        for w in self._insights_frame.winfo_children():
            w.destroy()

        if not insights:
            self._show_no_insights()
            return

        for ins in insights:
            row = ctk.CTkFrame(self._insights_frame, fg_color=C["panel"], corner_radius=6)
            row.pack(fill=tk.X, pady=3)

            hint_colors = {
                "top": C["danger"], "form": C["warning"],
                "search": C["accent"], "password": C["danger"], "": C["accent"],
            }
            bar_color = hint_colors.get(ins.highlight_hint, C["accent"])
            ctk.CTkFrame(row, fg_color=bar_color, width=4, corner_radius=0).pack(side=tk.LEFT, fill=tk.Y)

            content = ctk.CTkFrame(row, fg_color=C["panel"])
            content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=SP["sm"] + 2, pady=SP["sm"])

            top = ctk.CTkFrame(content, fg_color=C["panel"])
            top.pack(fill=tk.X)

            ctk.CTkLabel(top, text=ins.label, text_color=C["text"], fg_color=C["panel"],
                         font=make_font(10, "bold")).pack(side=tk.LEFT)

            pct = int(ins.confidence * 100)
            pct_color = C["success"] if pct >= 60 else C["warning"] if pct >= 30 else C["danger"]

            # Confidence badge with bar visual
            conf_frame = ctk.CTkFrame(top, fg_color=C["panel"])
            conf_frame.pack(side=tk.RIGHT)

            conf_bar_bg = tk.Canvas(conf_frame, width=40, height=6, bg=C["panel_alt"],
                                    highlightthickness=0)
            conf_bar_bg.pack(side=tk.LEFT, padx=(0, SP["xs"]))
            bar_w = int(40 * ins.confidence)
            conf_bar_bg.create_rectangle(0, 0, bar_w, 6, fill=pct_color, outline="")

            ctk.CTkLabel(conf_frame, text=f"{pct}%", text_color=pct_color, fg_color=C["panel"],
                         font=make_font(9, "bold")).pack(side=tk.LEFT)

            if ins.keywords:
                kw_text = " · ".join(ins.keywords[:4])
                ctk.CTkLabel(content, text=kw_text, text_color=C["muted"], fg_color=C["panel"],
                             font=make_font(8), wraplength=260, justify=tk.LEFT).pack(fill=tk.X, pady=(2, SP["xs"]))

            ctk.CTkLabel(content, text=ins.suggestion, text_color=C["dim"], fg_color=C["panel"],
                         font=make_font(8), wraplength=260, justify=tk.LEFT).pack(fill=tk.X)

    def _build_ocr_output(self, parent):
        self._ocr_text = scrolledtext.ScrolledText(
            parent, bg=C["panel"], fg=C["text"], insertbackground=C["accent"],
            font=make_mono(9), wrap=tk.WORD, relief="flat", state=tk.DISABLED,
            bd=0, highlightthickness=0
        )
        self._ocr_text.pack(fill=tk.BOTH, expand=True)

    def _build_log_console(self):
        log_card = make_card(self.root)
        log_card.pack(fill=tk.X, padx=SP["xl"], pady=SP["lg"] - 2)

        log_header = make_card_header(log_card, "System Journal", icon="▪")

        flush_btn = ctk.CTkButton(
            log_header, text="Flush", fg_color=C["panel"], text_color=C["muted"],
            hover_color=C["panel_alt"], corner_radius=4, command=self._clear_log, width=50, height=20,
            font=make_font(8)
        )
        flush_btn.pack(side=tk.RIGHT)

        self._log_text = tk.Text(
            log_card, bg=C["panel"], fg=C["muted"], insertbackground=C["accent"],
            font=make_mono(8), wrap=tk.WORD, relief="flat", state=tk.DISABLED,
            height=5, bd=0, highlightthickness=0
        )
        self._log_text.pack(fill=tk.X, padx=SP["md"], pady=(0, SP["sm"] + 2))

        self._log_text.tag_configure("INFO", foreground=C["text"])
        self._log_text.tag_configure("OK",   foreground=C["success"])
        self._log_text.tag_configure("WARN", foreground=C["warning"])
        self._log_text.tag_configure("ERR",  foreground=C["danger"])
        self._log_text.tag_configure("DEV",  foreground=C["accent"])
        self._log_text.tag_configure("ts",   foreground=C["dim"])
        self._log_text.tag_configure("icon", foreground=C["muted"])

        self._log("Daemon initialized with graphite shell", "DEV")
        self._log(f"OCR Pipeline: {'ONLINE' if self.ocr.available else 'OFFLINE'}", "OK" if self.ocr.available else "ERR")

    def _build_statusbar(self):
        bar = ctk.CTkFrame(self.root, fg_color=C["surface"], height=28, corner_radius=0)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar.pack_propagate(False)

        self._status_lbl = ctk.CTkLabel(
            bar, text="Ready · Define capture bounding box to start",
            text_color=C["muted"], fg_color=C["surface"], font=make_font(8), anchor="w"
        )
        self._status_lbl.pack(side=tk.LEFT, padx=SP["lg"])

        ocr_txt = "OCR ONLINE" if self.ocr.available else "OCR MISSING"
        ocr_color = C["success"] if self.ocr.available else C["danger"]
        ctk.CTkLabel(bar, text=ocr_txt, text_color=ocr_color, fg_color=C["surface"],
                     font=make_font(8, "bold")).pack(side=tk.RIGHT, padx=SP["lg"])

        tts_txt = "TTS ONLINE" if self.voice.available else "TTS OFF"
        tts_color = C["success"] if self.voice.available else C["dim"]
        ctk.CTkLabel(bar, text=tts_txt, text_color=tts_color, fg_color=C["surface"],
                     font=make_font(8, "bold")).pack(side=tk.RIGHT, padx=SP["sm"])

    # ═══════════════════════════════════════════════════════════════════
    #   Helpers & Animations
    # ═══════════════════════════════════════════════════════════════════

    def _apply_style(self):
        style_scale_dark(self.root)

    # ═══════════════════════════════════════════════════════════════════
    #   Event handlers
    # ═══════════════════════════════════════════════════════════════════

    def _kb_space(self):
        if self._session_active:
            self._pause_session()

    def _select_region(self):
        self._set_status("Awaiting manual region select…")
        self._log("Invoking region selector modal…", "INFO")
        self.root.after(150, self._do_select_region)

    def _do_select_region(self):
        sel = self.region_selector.select()
        if sel:
            self._region = sel
            self._region_lbl.configure(
                text=f"{sel['width']}×{sel['height']} px  at  ({sel['left']}, {sel['top']})",
                text_color=C["accent"],
            )
            self.capture.set_region(sel["left"], sel["top"], sel["width"], sel["height"])
            self._set_status("Region bound. Ready to begin.", C["success"])
            self._log(f"Region bound: {sel['width']}x{sel['height']} offset=({sel['left']},{sel['top']})", "OK")
        else:
            self._set_status("Region selection dismissed.")
            self._log("Region selection dismissed.", "WARN")

    def _start_session(self):
        if self._region is None:
            self._set_status("Select target region prior to execution.", C["warning"])
            self._log("Execution rejected — no region defined.", "WARN")
            return

        if self._paused:
            self._paused = False
            self.capture.resume()
            if self._show_overlay.get():
                self.overlay.show()
            self._update_session_buttons(running=True, paused=False)
            self._set_status("Session active.", C["success"])
            self._log("Capture loop resumed.", "OK")
            return

        self._session_active = True
        self._paused = False
        self._frame_count = 0
        self._session_start = time.time()
        self._last_frame_time = None
        self._pulse_step = 0

        # Create a memory session for DB storage
        try:
            self._current_session_id = self.db.create_session()
        except Exception:
            self._current_session_id = None

        self.capture.set_callback(self._on_frame)
        self.capture.fps = self._fps_var.get()
        self.capture.start()

        if self._show_overlay.get():
            self.overlay.show()

        self._update_session_buttons(running=True, paused=False)
        self._set_status("Session active — polling screen buffer…", C["success"])
        self._log(f"Stream initiated @ {self._fps_var.get():.1f} FPS", "OK")

        if self.voice.available and self._voice_enabled.get():
            self.voice.speak("Screen monitoring active.")

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
        self._set_status("Session paused.", C["warning"])
        self._log("Capture loop paused.", "WARN")
        self._fps_meter_lbl.configure(text="0.0")

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
        self._set_status("Session terminated.")
        self._timer_lbl.configure(text="00:00:00", text_color=C["muted"])
        self._fps_meter_lbl.configure(text="0.0")
        self._dot_canvas.itemconfig(self._dot_circle, fill=C["dim"])
        self._dot_canvas.itemconfig(self._dot_glow, outline=C["dim"])

        self._draw_idle_preview()
        self._show_no_insights()

        if was_active:
            self._log("Session halted.", "INFO")

    def _update_session_buttons(self, running: bool, paused: bool):
        if not running:
            self._btn_start.configure(state="normal", text="▶  Start", fg_color=C["accent"])
            self._btn_pause.configure(state="disabled", text="⏸  Pause")
            self._btn_stop.configure(state="disabled")
        elif paused:
            self._btn_start.configure(state="normal", text="▶  Resume", fg_color=C["success"])
            self._btn_pause.configure(state="normal", text="⏸  Paused")
            self._btn_stop.configure(state="normal")
        else:
            self._btn_start.configure(state="disabled", text="▶  Running", fg_color=C["border"])
            self._btn_pause.configure(state="normal", text="⏸  Pause")
            self._btn_stop.configure(state="normal")

    def _toggle_voice(self):
        self.voice.set_enabled(self._voice_enabled.get())
        self._log(f"Voice engine toggled {'ON' if self._voice_enabled.get() else 'OFF'}.", "INFO")

    def _toggle_overlay(self):
        if self._show_overlay.get() and self._session_active and not self._paused:
            self.overlay.show()
        else:
            self.overlay.hide()
        self._log(f"Display overlay {'activated' if self._show_overlay.get() else 'hidden'}.", "INFO")

    def _fps_changed(self, _=None):
        fps = round(self._fps_var.get(), 1)
        self._fps_lbl.configure(text=str(fps))
        self.capture.fps = fps

    def _clear_ocr(self):
        self._ocr_text.config(state=tk.NORMAL)
        self._ocr_text.delete("1.0", tk.END)
        self._ocr_text.config(state=tk.DISABLED)
        self._log("OCR buffer cleared.", "INFO")

    def _clear_log(self):
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state=tk.DISABLED)

    def _log(self, msg: str, level: str = "INFO"):
        try:
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            icon = LOG_ICONS.get(level, "●")
            self._log_text.config(state=tk.NORMAL)
            self._log_text.insert(tk.END, f"[{ts}] ", "ts")
            self._log_text.insert(tk.END, f"{icon} ", level)
            self._log_text.insert(tk.END, f"{msg}\n", "INFO")
            self._log_text.see(tk.END)
            self._log_text.config(state=tk.DISABLED)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════
    #   Pipeline
    # ═══════════════════════════════════════════════════════════════════

    def _on_frame(self, image):
        t0 = time.time()
        boxes = self.ocr.extract_boxes(image)
        raw_text = " ".join([b.text for b in boxes if b.text.strip()]) if boxes else ""

        pii_res = self.pii.redact_text(raw_text)
        redacted_text = pii_res.redacted_text
        redacted_boxes, _pii_entities = self.pii.redact_boxes(boxes)

        if self._session_active and self._current_session_id and redacted_text:
            try:
                title, app = get_foreground_window_info()
                self.db.add_record(
                    session_id=self._current_session_id,
                    redacted_text=redacted_text,
                    app_name=app or "Desktop",
                    window_title=title or "Active Window",
                    is_active=True,
                    token_count=max(len(redacted_text.split()), 1),
                )
            except Exception:
                pass

        insights = self.analyzer.analyze(redacted_text)
        ocr_time = time.time() - t0
        self.root.after(0, lambda: self._update_ui(image, redacted_text, insights, ocr_time, redacted_boxes))

    def _update_ui(self, image, text: str, insights, ocr_time: float = 0.0, redacted_boxes=None):
        now = time.time()
        if self._last_frame_time:
            delta = now - self._last_frame_time
            self._actual_fps = round(1.0 / delta, 1) if delta > 0 else 0.0
            self._fps_meter_lbl.configure(text=f"{self._actual_fps:.1f}")
        self._last_frame_time = now

        self._frame_count += 1
        self._frame_count_lbl.configure(text=f"{self._frame_count} frames")

        self._render_preview(image)

        if text != self._last_text and text:
            self._last_text = text
            self._append_ocr(text)
            self._log(f"OCR processed {len(text)} chars in {ocr_time*1000:.0f}ms", "DEV")

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
        self._preview_canvas.create_image(cw // 2, ch // 2, anchor=tk.CENTER, image=self._preview_photo)

    def _append_ocr(self, text: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._ocr_text.config(state=tk.NORMAL)
        self._ocr_text.insert(tk.END, f"\n[{ts}]\n{text}\n")
        self._ocr_text.see(tk.END)
        self._ocr_text.config(state=tk.DISABLED)

    # ═══════════════════════════════════════════════════════════════════
    #   Ticker
    # ═══════════════════════════════════════════════════════════════════

    def _tick(self):
        try:
            if not self.root.winfo_exists():
                return
        except Exception:
            return

        if self._session_active and not self._paused and self._session_start:
            elapsed = int(time.time() - self._session_start)
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            self._timer_lbl.configure(text=f"{h:02d}:{m:02d}:{s:02d}", text_color=C["accent"])

            # Pulsing status dot with glow ring
            color = self._pulse_colors[self._pulse_step % len(self._pulse_colors)]
            self._dot_canvas.itemconfig(self._dot_circle, fill=color)
            glow = lerp_color(C["surface"], C["success"], 0.15 + 0.35 * ((math.sin(self._pulse_step * 0.2) + 1) / 2))
            self._dot_canvas.itemconfig(self._dot_glow, outline=glow)
            self._pulse_step += 1

        elif self._paused:
            self._dot_canvas.itemconfig(self._dot_circle, fill=C["warning"])
            self._dot_canvas.itemconfig(self._dot_glow, outline=lerp_color(C["surface"], C["warning"], 0.3))

        try:
            if self.root.winfo_exists():
                self.root.after(40, self._tick)  # 25 FPS UI refresh loop
        except Exception:
            pass

    def _resize_preview(self, event):
        if not self._session_active:
            self._draw_idle_preview(event.width, event.height)

    def _set_status(self, msg: str, color: str = None):
        self._status_lbl.configure(text=msg, text_color=color or C["muted"])

    def _on_close(self):
        self.capture.stop()
        self.voice.stop()
        self.overlay.hide()
        # Clean up background monitors
        try:
            self.blocklist_monitor.stop()
        except Exception:
            pass
        try:
            self.trigger_controller.stop()
        except Exception:
            pass
        try:
            self.db.close()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()

    # ═══════════════════════════════════════════════════════════════════
    #   DFA & LLM Queue Handlers
    # ═══════════════════════════════════════════════════════════════════

    def _on_dfa_state_changed(self, source, target, trigger, payload=None):
        try:
            self.root.after(0, lambda: self._apply_dfa_state(source, target, trigger, payload))
        except Exception:
            pass

    def _apply_dfa_state(self, source, target, trigger, payload=None):
        from src.state_machine import State, Trigger
        color_map = {
            State.DORMANT: C["dim"],
            State.ACTIVE: C["accent"],
            State.PAUSED: C["warning"],
            State.SUMMARIZING: C["dev"],
        }
        if hasattr(self, "_state_badge"):
            self._state_badge.configure(
                text=f"[{target.value.upper()}]",
                text_color=color_map.get(target, C["dim"]),
            )

        if target == State.PAUSED:
            self._paused = True
            self._update_session_buttons(running=True, paused=True)
            self.overlay.hide()
            if trigger == Trigger.BLOCK_MATCH:
                app_info = f" ({payload.get('window') or payload.get('app')})" if isinstance(payload, dict) else ""
                self._set_status(f"Privacy suppression triggered{app_info}.", C["warning"])
                if hasattr(self, "_log"):
                    self._log(f"Window blocklist matched:{app_info}", "WARN")

        elif target == State.DORMANT:
            if self._session_active or self._paused:
                self._session_active = False
                self._paused = False
                self._update_session_buttons(running=False, paused=False)
                self.overlay.clear()
                self.overlay.hide()
                if trigger == Trigger.TIMEOUT:
                    self._set_status("Capture watchdog timed out due to inactivity.", C["warning"])
                    if hasattr(self, "_log"):
                        self._log("Inactivity watchdog -> DORMANT", "WARN")
                else:
                    self._set_status("Session stopped.")

        elif target == State.ACTIVE:
            self._session_active = True
            self._paused = False
            self._update_session_buttons(running=True, paused=False)

    def _drain_llm_queue(self):
        try:
            while True:
                msg_type, content = self._llm_queue.get_nowait()
                if msg_type == "clear":
                    if hasattr(self, "overlay"):
                        self.overlay.clear_llm_response()
                    if hasattr(self, "_llm_response_text"):
                        self._llm_response_text.configure(state="normal")
                        self._llm_response_text.delete("1.0", "end")
                        self._llm_response_text.configure(state="disabled")
                elif msg_type == "chunk":
                    if hasattr(self, "overlay"):
                        self.overlay.append_llm_chunk(content)
                    if hasattr(self, "_llm_response_text"):
                        self._llm_response_text.configure(state="normal")
                        self._llm_response_text.insert("end", content)
                        self._llm_response_text.see("end")
                        self._llm_response_text.configure(state="disabled")
                elif msg_type == "done":
                    self._is_llm_streaming = False
                    if hasattr(self, "_ask_btn"):
                        self._ask_btn.configure(state="normal")
                    if hasattr(self, "_log"):
                        self._log(f"LLM Context query completed ({len(content)} chars)", "INFO")
                    return
        except Exception:
            pass
        if self._is_llm_streaming:
            try:
                if self.root.winfo_exists():
                    self.root.after(40, self._drain_llm_queue)
            except Exception:
                pass

    def _submit_query(self, query: str | None = None):
        if query is None and hasattr(self, "_ask_entry"):
            query = self._ask_entry.get().strip()
        if not query or self._is_llm_streaming:
            return

        self._is_llm_streaming = True
        if hasattr(self, "_ask_btn"):
            self._ask_btn.configure(state="disabled")

        if hasattr(self, "_llm_response_text"):
            self._llm_response_text.configure(state="normal")
            self._llm_response_text.delete("1.0", "end")
            self._llm_response_text.insert("end", "Querying episodic memory store...\n")
            self._llm_response_text.configure(state="disabled")

        if hasattr(self, "_log"):
            self._log(f"Query: {query}", "INFO")

        if hasattr(self, "_show_overlay") and self._show_overlay.get():
            self.overlay.show()
            self.overlay.show_llm_response(text="Querying context engine...", header="BH-AI Privacy Assistant")

        def _worker():
            try:
                full_text = ""
                self._llm_queue.put(("clear", ""))
                for chunk in self.llm.stream_with_rag(query, self.rag, session_id=self._current_session_id):
                    full_text += chunk
                    self._llm_queue.put(("chunk", chunk))
                self._llm_queue.put(("done", full_text))
            except Exception as exc:
                self._llm_queue.put(("chunk", f"\n\n[Inference Error: {exc}]"))
                self._llm_queue.put(("done", ""))

        threading.Thread(target=_worker, daemon=True).start()
        self.root.after(40, self._drain_llm_queue)