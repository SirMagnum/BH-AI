"""
BH-AI — User Mode UI
A compact, floating always-on-top pill HUD.
Pick a window → click Start. Zero complexity.
Features a minimalist graphite theme and rounded pill shape.
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
import datetime
import ctypes
import ctypes.wintypes
from PIL import Image, ImageTk

from src.capture import ScreenCapture
from src.ocr import OCRProcessor
from src.analyzer import ContextAnalyzer, Insight
from src.voice import VoiceFeedback
from src.overlay import OverlayWindow
from src.privacy import PIIRedactor, WindowBlocklistMonitor, get_foreground_window_info
from src.memory import MemoryDatabase, EmbeddingEngine, EpisodicRAGEngine
from src.reasoning import LocalLLMDriver, LLMBackend
from src.voice import VoiceTriggerController


from src.ui_theme import (
    ctk, C, SPACING, make_font, make_mono, create_rounded_rect,
    gen_sine_pulse, lerp_color, style_combobox_dark,
)

SP = SPACING

# ────────────────────────────── window enumeration ─────────────────────────

def _enum_windows() -> list[dict]:
    results = []

    EnumWindows       = ctypes.windll.user32.EnumWindows
    GetWindowTextW    = ctypes.windll.user32.GetWindowTextW
    GetWindowTextLenW = ctypes.windll.user32.GetWindowTextLengthW
    IsWindowVisible   = ctypes.windll.user32.IsWindowVisible
    IsIconic          = ctypes.windll.user32.IsIconic
    GetWindowRect     = ctypes.windll.user32.GetWindowRect

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    def callback(hwnd, _):
        if not IsWindowVisible(hwnd):
            return True
        if IsIconic(hwnd):
            return True
        length = GetWindowTextLenW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return True

        rect = ctypes.wintypes.RECT()
        GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w < 50 or h < 50:
            return True

        results.append({
            "hwnd":   hwnd,
            "title":  title,
            "left":   rect.left,
            "top":    rect.top,
            "width":  w,
            "height": h,
        })
        return True

    EnumWindows(WNDENUMPROC(callback), 0)
    return results


# ────────────────────────────── User Mode UI ───────────────────────────────

STATE_COLORS = {
    "idle":    C["border"],
    "active":  C["accent"],
    "paused":  C["warning"],
    "danger":  C["danger"],
}

PULSE_STEPS = 20

class UserModeUI:

    PILL_W = 580
    PILL_H = 86
    THUMB_W = 130
    THUMB_H = 72
    RADIUS = 20

    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("BH-AI")
        self.root.geometry(f"{self.PILL_W}x{self.PILL_H}+80+80")
        self.root.minsize(self.PILL_W, self.PILL_H)
        self.root.maxsize(self.PILL_W, self.PILL_H)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        
        # Transparent background for rounded corners
        self.root.configure(bg=C["transparent"])
        self.root.wm_attributes("-transparentcolor", C["transparent"])

        # ── state ──
        self._session_active = False
        self._paused = False
        self._region: dict | None = None
        self._selected_window: dict | None = None
        self._frame_count = 0
        self._session_start: float | None = None
        self._pulse_step = 0
        self._state = "idle"
        self._voice_enabled = tk.BooleanVar(value=True)
        self._fps_var = tk.DoubleVar(value=1.0)
        self._last_text = ""
        self._windows: list[dict] = []
        self._preview_photo = None

        # pulse color tables
        self._pulse_tables = {
            state: self._make_pulse(color, PULSE_STEPS)
            for state, color in STATE_COLORS.items()
        }

        # ── modules ──
        self.capture = ScreenCapture(fps=1.0)
        self.ocr = OCRProcessor()
        self.analyzer = ContextAnalyzer()
        self.voice = VoiceFeedback()
        self.overlay = OverlayWindow(self.root)
        # local reasoning, privacy & memory engines
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

        # ── build ──
        self._build_pill()
        self._make_draggable()

        # ── Dark-mode styling for ttk widgets ──
        self._combobox_style = style_combobox_dark(self.root)

        # ── kick off ──
        self._refresh_windows()
        self._tick()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════════════════════════════════
    #   Build pill
    # ═══════════════════════════════════════════════════════════════════

    def _build_pill(self):
        # Outer canvas for the pill shape
        self._canvas = tk.Canvas(
            self.root,
            width=self.PILL_W, height=self.PILL_H,
            bg=C["transparent"],
            highlightthickness=0,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # Draw the main pill background
        self._pill_bg = create_rounded_rect(
            self._canvas, 2, 2, self.PILL_W - 2, self.PILL_H - 2,
            radius=self.RADIUS, fill=C["surface"], outline=STATE_COLORS["idle"], width=2
        )

        # Inner container placed on canvas
        inner = ctk.CTkFrame(self._canvas, fg_color=C["surface"])
        self._canvas.create_window(
            self.PILL_W // 2, self.PILL_H // 2,
            window=inner, width=self.PILL_W - 20, height=self.PILL_H - 16,
        )

        # ── left: logo ──────────────────────────────────────────────
        logo_frame = ctk.CTkFrame(inner, fg_color=C["surface"])
        logo_frame.pack(side=tk.LEFT, padx=(6, 0))

        self._dot_canvas = tk.Canvas(logo_frame, width=14, height=14,
                                      bg=C["surface"], highlightthickness=0)
        self._dot_canvas.pack(side=tk.TOP, pady=(SP["lg"], 2))
        # Glow ring + dot
        self._dot_glow = self._dot_canvas.create_oval(0, 0, 13, 13, fill="", outline=C["dim"], width=1)
        self._dot_oval = self._dot_canvas.create_oval(3, 3, 11, 11, fill=C["muted"], outline="")

        ctk.CTkLabel(logo_frame, text="BH", text_color=C["accent"], fg_color=C["surface"],
                 font=make_font(10, "bold")).pack(side=tk.TOP)

        # ── center: window picker ───────────────────────────────────
        center = ctk.CTkFrame(inner, fg_color=C["surface"])
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=SP["md"])

        picker_row = ctk.CTkFrame(center, fg_color=C["surface"])
        picker_row.pack(fill=tk.X, pady=(SP["md"], SP["xs"]))

        ctk.CTkLabel(picker_row, text="Monitor window:", text_color=C["muted"],
                 fg_color=C["surface"], font=make_font(9)).pack(side=tk.LEFT)

        refresh_btn = ctk.CTkLabel(picker_row, text="↻", text_color=C["accent"],
                               fg_color=C["surface"], font=make_font(12), cursor="hand2")
        refresh_btn.pack(side=tk.RIGHT, padx=(SP["xs"], 0))
        refresh_btn.bind("<Button-1>", lambda e: self._refresh_windows())
        refresh_btn.bind("<Enter>", lambda e: refresh_btn.configure(text_color=C["accent_hov"]))
        refresh_btn.bind("<Leave>", lambda e: refresh_btn.configure(text_color=C["accent"]))

        self._window_var = tk.StringVar(value="— select a window —")
        self._window_menu = ttk.Combobox(
            center,
            textvariable=self._window_var,
            state="readonly",
            font=make_font(10),
            width=32,
        )
        self._window_menu.pack(fill=tk.X, pady=(0, SP["sm"]))
        self._window_menu.bind("<<ComboboxSelected>>", self._on_window_selected)

        # ── right: controls + thumbnail ─────────────────────────────
        right = ctk.CTkFrame(inner, fg_color=C["surface"])
        right.pack(side=tk.RIGHT, padx=(SP["xs"], SP["sm"]))

        # Thumbnail
        self._thumb_canvas = tk.Canvas(right, width=self.THUMB_W,
                                        height=self.THUMB_H - 16,
                                        bg=C["panel"],
                                        highlightthickness=1,
                                        highlightbackground=C["border"])
        self._thumb_canvas.pack(side=tk.LEFT, padx=(0, SP["md"]))
        self._thumb_no_text = self._thumb_canvas.create_text(
            self.THUMB_W // 2, (self.THUMB_H - 16) // 2,
            text="No preview", fill=C["muted"], font=make_font(8), justify=tk.CENTER,
        )

        # Control buttons + timer
        ctrl = ctk.CTkFrame(right, fg_color=C["surface"])
        ctrl.pack(side=tk.LEFT)

        btn_row = ctk.CTkFrame(ctrl, fg_color=C["surface"])
        btn_row.pack(pady=(SP["xs"], SP["xs"]))

        self._btn_start = ctk.CTkButton(
            btn_row, text="▶", fg_color=C["success"], text_color=C["surface"],
            command=self._start_session, width=32, height=32, corner_radius=16, font=make_font(11, "bold")
        )
        self._btn_start.pack(side=tk.LEFT, padx=3)

        self._btn_pause = ctk.CTkButton(
            btn_row, text="⏸", fg_color=C["warning"], text_color=C["surface"],
            command=self._pause_session, state="disabled", width=32, height=32, corner_radius=16, font=make_font(11, "bold")
        )
        self._btn_pause.pack(side=tk.LEFT, padx=3)

        self._btn_stop = ctk.CTkButton(
            btn_row, text="⏹", fg_color=C["danger"], text_color=C["surface"],
            command=self._stop_session, state="disabled", width=32, height=32, corner_radius=16, font=make_font(11, "bold")
        )
        self._btn_stop.pack(side=tk.LEFT, padx=3)

        # Settings gear
        gear = ctk.CTkLabel(btn_row, text="⚙", text_color=C["muted"], fg_color=C["surface"],
                        font=make_font(14), cursor="hand2")
        gear.pack(side=tk.LEFT, padx=(SP["sm"], 0))
        gear.bind("<Button-1>", lambda e: self._open_settings())
        gear.bind("<Enter>", lambda e: gear.configure(text_color=C["text"]))
        gear.bind("<Leave>", lambda e: gear.configure(text_color=C["muted"]))

        # Timer label & status
        self._timer_lbl = ctk.CTkLabel(ctrl, text="00:00:00",
                                    text_color=C["muted"], fg_color=C["surface"],
                                    font=make_font(10, "bold"))
        self._timer_lbl.pack()

        self._status_lbl = ctk.CTkLabel(ctrl, text="Select a window",
                                     text_color=C["dim"], fg_color=C["surface"],
                                     font=make_font(8))
        self._status_lbl.pack()

        # ── close button (top-right corner on canvas) ────────────────
        close_btn = ctk.CTkLabel(
            self._canvas, text="✕", text_color=C["muted"],
            fg_color=C["surface"], font=make_font(10, "bold"), cursor="hand2",
        )
        close_btn.place(x=self.PILL_W - 24, y=8)
        close_btn.bind("<Button-1>", lambda e: self._on_close())
        close_btn.bind("<Enter>", lambda e: close_btn.configure(text_color=C["danger"]))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(text_color=C["muted"]))

    # ═══════════════════════════════════════════════════════════════════
    #   Draggable window
    # ═══════════════════════════════════════════════════════════════════

    def _make_draggable(self):
        self._drag_x = 0
        self._drag_y = 0

        def on_press(e):
            self._drag_x = e.x_root - self.root.winfo_x()
            self._drag_y = e.y_root - self.root.winfo_y()

        def on_drag(e):
            x = e.x_root - self._drag_x
            y = e.y_root - self._drag_y
            self.root.geometry(f"+{x}+{y}")

        self._canvas.bind("<ButtonPress-1>",   on_press)
        self._canvas.bind("<B1-Motion>",       on_drag)

    # ═══════════════════════════════════════════════════════════════════
    #   Widget helpers
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def _make_pulse(base: str, steps: int) -> list[str]:
        try:
            r = int(base[1:3], 16)
            g = int(base[3:5], 16)
            b = int(base[5:7], 16)
            colors = []
            for i in range(steps):
                t = i / (steps - 1)
                factor = (1 - abs(2 * t - 1)) ** 0.6
                nr = max(15, int(r * factor))
                ng = max(15, int(g * factor))
                nb = max(15, int(b * factor))
                colors.append(f"#{min(nr,255):02x}{min(ng,255):02x}{min(nb,255):02x}")
            return colors
        except Exception:
            return [base] * steps

    # ═══════════════════════════════════════════════════════════════════
    #   Window enumeration
    # ═══════════════════════════════════════════════════════════════════

    def _refresh_windows(self):
        self._windows = _enum_windows()
        titles = [w["title"][:55] + ("…" if len(w["title"]) > 55 else "")
                  for w in self._windows]
        self._window_menu["values"] = titles if titles else ["(no windows found)"]

        # Apply dark styling to combobox after values are set
        if hasattr(self, '_combobox_style'):
            self._window_menu.configure(style=self._combobox_style)

        if not self._selected_window:
            self._window_var.set("— select a window —")

    def _on_window_selected(self, _=None):
        idx = self._window_menu.current()
        if 0 <= idx < len(self._windows):
            w = self._windows[idx]
            self._selected_window = w
            self._region = {
                "left": w["left"], "top": w["top"],
                "width": w["width"], "height": w["height"],
            }
            self.capture.set_region(w["left"], w["top"], w["width"], w["height"])
            self._set_status(f"Ready — {w['width']}×{w['height']}")
            self._canvas.itemconfig(self._pill_bg, outline=C["accent"])
            self.root.after(600, self._restore_border)

    def _restore_border(self):
        self._canvas.itemconfig(self._pill_bg, outline=STATE_COLORS[self._state])

    # ═══════════════════════════════════════════════════════════════════
    #   Session control
    # ═══════════════════════════════════════════════════════════════════

    def _start_session(self):
        if self._region is None:
            self._set_status("⚠ Pick a window first!")
            self._canvas.itemconfig(self._pill_bg, outline=C["warning"])
            self.root.after(800, self._restore_border)
            return

        if self._paused:
            self._paused = False
            self.capture.resume()
            self.overlay.show()
            self._set_state("active")
            self._update_btns(running=True, paused=False)
            self._set_status("Resumed")
            return

        self._session_active = True
        self._paused = False
        self._frame_count = 0
        self._session_start = time.time()

        # Create a memory session for DB storage
        try:
            self._current_session_id = self.db.create_session()
        except Exception:
            self._current_session_id = None

        self.capture.set_callback(self._on_frame)
        self.capture.fps = self._fps_var.get()
        self.capture.start()
        self.overlay.show()

        self._set_state("active")
        self._update_btns(running=True, paused=False)
        self._set_status("Monitoring…")

        if self.voice.available and self._voice_enabled.get():
            self.voice.speak("Monitoring started.")

    def _pause_session(self):
        if not self._session_active:
            return
        if self._paused:
            self._start_session()
            return

        self._paused = True
        self.capture.pause()
        self.overlay.hide()
        self._set_state("paused")
        self._update_btns(running=True, paused=True)
        self._set_status("Paused")

    def _stop_session(self):
        if not self._session_active and not self._paused:
            return

        self._session_active = False
        self._paused = False
        self._session_start = None

        self.capture.stop()
        self.overlay.clear()
        self.overlay.hide()

        self._set_state("idle")
        self._update_btns(running=False, paused=False)
        self._set_status("Stopped — pick a window")
        self._timer_lbl.configure(text="00:00:00", text_color=C["muted"])

        # Clear thumbnail
        self._thumb_canvas.delete("all")
        self._thumb_no_text = self._thumb_canvas.create_text(
            self.THUMB_W // 2, (self.THUMB_H - 16) // 2,
            text="No preview", fill=C["muted"], font=make_font(8), justify=tk.CENTER,
        )

    def _update_btns(self, running: bool, paused: bool):
        if not running:
            self._btn_start.configure(state="normal")
            self._btn_pause.configure(state="disabled")
            self._btn_stop.configure(state="disabled")
        elif paused:
            self._btn_start.configure(state="normal")
            self._btn_pause.configure(state="normal")
            self._btn_stop.configure(state="normal")
        else:
            self._btn_start.configure(state="disabled")
            self._btn_pause.configure(state="normal")
            self._btn_stop.configure(state="normal")

    def _set_state(self, state: str):
        self._state = state
        self._canvas.itemconfig(self._pill_bg, outline=STATE_COLORS.get(state, STATE_COLORS["idle"]))

    def _set_status(self, msg: str):
        self._status_lbl.configure(text=msg)

    # ═══════════════════════════════════════════════════════════════════
    #   Settings popup
    # ═══════════════════════════════════════════════════════════════════

    def _open_settings(self):
        if hasattr(self, "_settings_win") and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return

        win = tk.Toplevel(self.root)
        self._settings_win = win
        win.title("Settings")
        win.configure(bg=C["panel"])
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.overrideredirect(True)

        px = self.root.winfo_x() + self.PILL_W + 12
        py = self.root.winfo_y()
        win.geometry(f"240x180+{px}+{py}")
        
        # Border canvas
        set_canvas = tk.Canvas(win, bg=C["transparent"], highlightthickness=0)
        set_canvas.pack(fill=tk.BOTH, expand=True)
        create_rounded_rect(set_canvas, 1, 1, 239, 179, radius=12, fill=C["surface"], outline=C["border"])
        
        inner = ctk.CTkFrame(set_canvas, fg_color=C["surface"])
        set_canvas.create_window(120, 90, window=inner, width=230, height=170)

        # Header
        hdr = ctk.CTkFrame(inner, fg_color=C["surface"])
        hdr.pack(fill=tk.X)
        ctk.CTkLabel(hdr, text="⚙  Settings", text_color=C["accent"],
                 fg_color=C["surface"], font=make_font(11, "bold"),
                 anchor="w", padx=SP["md"], pady=SP["sm"] + 2).pack(side=tk.LEFT)
        close_set = ctk.CTkLabel(hdr, text="✕", text_color=C["muted"], fg_color=C["surface"], font=make_font(10), cursor="hand2")
        close_set.pack(side=tk.RIGHT, padx=SP["md"], pady=SP["sm"] + 2)
        close_set.bind("<Button-1>", lambda e: win.destroy())
        close_set.bind("<Enter>", lambda e: close_set.configure(text_color=C["danger"]))
        close_set.bind("<Leave>", lambda e: close_set.configure(text_color=C["muted"]))
        
        ctk.CTkFrame(inner, fg_color=C["border"], height=1).pack(fill=tk.X)

        body = ctk.CTkFrame(inner, fg_color=C["surface"])
        body.pack(fill=tk.BOTH, expand=True)

        # Voice toggle
        ctk.CTkCheckBox(
            body, text="Voice feedback",
            variable=self._voice_enabled,
            text_color=C["text"], fg_color=C["accent"],
            font=make_font(10),
            command=lambda: self.voice.set_enabled(self._voice_enabled.get()),
        ).pack(anchor="w", pady=SP["xs"])

        # FPS slider
        fps_row = ctk.CTkFrame(body, fg_color=C["surface"])
        fps_row.pack(fill=tk.X, pady=(SP["sm"], 0))
        ctk.CTkLabel(fps_row, text="Capture FPS:", text_color=C["muted"],
                 fg_color=C["surface"], font=make_font(9)).pack(side=tk.LEFT)
        self._settings_fps_lbl = ctk.CTkLabel(fps_row, text=f"{self._fps_var.get():.1f}",
                                           text_color=C["accent"], fg_color=C["surface"],
                                           font=make_font(10, "bold"))
        self._settings_fps_lbl.pack(side=tk.RIGHT)

        def _fps_upd(v):
            fps = round(float(v), 1)
            self._fps_var.set(fps)
            self.capture.fps = fps
            self._settings_fps_lbl.configure(text=f"{fps:.1f}")

        ttk.Style().configure("Horizontal.TScale",
                              background=C["surface"], troughcolor=C["panel"])
        ttk.Scale(body, from_=0.2, to=5.0, orient=tk.HORIZONTAL,
                  variable=self._fps_var, length=200,
                  command=_fps_upd).pack(fill=tk.X, pady=(SP["xs"], 0))

        # Refresh windows button
        ctk.CTkButton(
            body, text="↻  Refresh window list",
            text_color=C["text"], fg_color=C["panel"],
            hover_color=C["border"],
            font=make_font(9),
            command=self._refresh_windows,
        ).pack(fill=tk.X, pady=(SP["lg"], 0))

    # ═══════════════════════════════════════════════════════════════════
    #   Frame processing
    # ═══════════════════════════════════════════════════════════════════

    def _on_frame(self, image: Image.Image):
        """Process frame with full privacy pipeline (extract_boxes + PII redaction)."""
        boxes = self.ocr.extract_boxes(image)
        raw_text = " ".join([b.text for b in boxes if b.text.strip()]) if boxes else ""

        pii_res = self.pii.redact_text(raw_text)
        redacted_text = pii_res.redacted_text

        # Store in memory DB if session active
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
        self.root.after(0, lambda: self._update_ui(image, redacted_text, insights))

    def _update_ui(self, image: Image.Image, text: str, insights: list[Insight]):
        self._frame_count += 1

        img_copy = image.copy()
        img_copy.thumbnail((self.THUMB_W, self.THUMB_H - 16), Image.LANCZOS)
        self._preview_photo = ImageTk.PhotoImage(img_copy)
        self._thumb_canvas.delete("all")
        self._thumb_canvas.create_image(
            self.THUMB_W // 2, (self.THUMB_H - 16) // 2,
            anchor=tk.CENTER, image=self._preview_photo,
        )

        if insights:
            hint = insights[0].highlight_hint
            if hint in ("top", "password"):
                self._canvas.itemconfig(self._pill_bg, outline=C["danger"])
            elif hint == "form":
                self._canvas.itemconfig(self._pill_bg, outline=C["warning"])
            else:
                self._canvas.itemconfig(self._pill_bg, outline=STATE_COLORS["active"])

        if text != self._last_text and text:
            self._last_text = text
            if insights and self._voice_enabled.get():
                summary = self.analyzer.summarize(insights)
                self.voice.speak(summary)

        if self._region:
            hint = insights[0].highlight_hint if insights else ""
            rect = self.overlay.build_region_rect(self._region, hint)
            self.overlay.set_rects([rect])

    # ═══════════════════════════════════════════════════════════════════
    #   Ticker
    # ═══════════════════════════════════════════════════════════════════

    def _tick(self):
        if self._session_active and not self._paused and self._session_start:
            elapsed = int(time.time() - self._session_start)
            h = elapsed // 3600
            m = (elapsed % 3600) // 60
            s = elapsed % 60
            self._timer_lbl.configure(
                text=f"{h:02d}:{m:02d}:{s:02d}",
                text_color=C["success"],
            )

        table = self._pulse_tables.get(self._state, self._pulse_tables["idle"])
        color = table[self._pulse_step % len(table)]
        self._dot_canvas.itemconfig(self._dot_oval, fill=color)
        # Animate glow ring
        if self._state != "idle":
            glow_t = 0.1 + 0.3 * ((self._pulse_step % PULSE_STEPS) / PULSE_STEPS)
            glow_color = lerp_color(C["surface"], STATE_COLORS.get(self._state, C["dim"]), glow_t)
            self._dot_canvas.itemconfig(self._dot_glow, outline=glow_color)
            self._pulse_step += 1
        else:
            self._dot_canvas.itemconfig(self._dot_glow, outline=C["dim"])

        try:
            if self.root.winfo_exists():
                self.root.after(80, self._tick)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════
    #   Cleanup
    # ═══════════════════════════════════════════════════════════════════

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


    def _on_dfa_state_changed(self, source, target, trigger, payload=None):
        try:
            self.root.after(0, lambda: self._apply_dfa_state(source, target, trigger, payload))
        except Exception:
            pass
            
    def _apply_dfa_state(self, source, target, trigger, payload=None):
        from src.state_machine import State, Trigger
        
        if target == State.ACTIVE:
            self._session_active = True
            self._paused = False
            self.overlay.show()
            self.overlay.set_state_badge(State.ACTIVE)
            self._set_state("active")
            if hasattr(self, "_update_btns"): self._update_btns(running=True, paused=False)
            self._set_status("Session active")
            
        elif target == State.PAUSED:
            self._paused = True
            if hasattr(self, "_update_btns"): self._update_btns(running=True, paused=True)
            self.overlay.hide()
            if trigger == Trigger.BLOCK_MATCH:
                app_info = ""
                if isinstance(payload, dict):
                    app_info = f" ({payload.get('window') or payload.get('app')})"
                self._set_state("paused")
                self._set_status(f"Auto-paused (Privacy){app_info}")
                
        elif target == State.DORMANT:
            self._session_active = False
            self._paused = False
            if hasattr(self, "_update_btns"): self._update_btns(running=False, paused=False)
            self.overlay.clear()
            self.overlay.hide()
            self._set_state("idle")
            if trigger == Trigger.TIMEOUT:
                self._set_status("Auto-stopped (Idle timeout)")
            else:
                self._set_status("Session stopped")

    def _drain_llm_queue(self):
        try:
            while True:
                msg_type, content = self._llm_queue.get_nowait()
                if msg_type == "clear":
                    self.overlay.clear_llm_response()
                elif msg_type == "chunk":
                    self.overlay.append_llm_chunk(content)
                elif msg_type == "done":
                    self._is_llm_streaming = False
                    return
        except Exception:
            pass
        if self._is_llm_streaming:
            self.root.after(50, self._drain_llm_queue)

    def _handle_voice_trigger(self, trigger_source: str):
        if self._is_llm_streaming:
            return

        self._set_status("AI Thinking")
        self._is_llm_streaming = True
        query = "What am I currently looking at or working on?"

        self.overlay.show()
        self.overlay.show_llm_response(text="Analyzing screen context with local RAG", header="BH-AI User Assistant")

        def _worker():
            try:
                full_text = ""
                self._llm_queue.put(("clear", ""))
                for chunk in self.llm.stream_with_rag(query, self.rag, session_id=self._current_session_id):
                    full_text += chunk
                    self._llm_queue.put(("chunk", chunk))
                self._llm_queue.put(("done", full_text))
            except Exception as exc:
                self._llm_queue.put(("chunk", f"\n\n[Error: {exc}]"))
                self._llm_queue.put(("done", ""))

        import threading
        threading.Thread(target=_worker, daemon=True).start()
        self.root.after(50, self._drain_llm_queue)
