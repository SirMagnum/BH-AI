"""
BH-AI — User Mode UI
A compact, floating always-on-top pill HUD.
Pick a window → click Start. Zero complexity.
Features a minimalist pastel theme and rounded pill shape.
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

from src.ui_theme import C, make_font, RoundedButton, create_rounded_rect

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
        self.root = tk.Tk()
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

        # ── build ──
        self._build_pill()
        self._make_draggable()

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
            bg=C["transparent"], highlightthickness=0,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # Draw the main pill background
        self._pill_bg = create_rounded_rect(
            self._canvas, 2, 2, self.PILL_W - 2, self.PILL_H - 2,
            radius=self.RADIUS, fill=C["surface"], outline=STATE_COLORS["idle"], width=2
        )

        # Inner container placed on canvas
        inner = tk.Frame(self._canvas, bg=C["surface"])
        self._canvas.create_window(
            self.PILL_W // 2, self.PILL_H // 2,
            window=inner, width=self.PILL_W - 20, height=self.PILL_H - 16,
        )

        # ── left: logo ──────────────────────────────────────────────
        logo_frame = tk.Frame(inner, bg=C["surface"])
        logo_frame.pack(side=tk.LEFT, padx=(6, 0))

        self._dot_canvas = tk.Canvas(logo_frame, width=12, height=12,
                                      bg=C["surface"], highlightthickness=0)
        self._dot_canvas.pack(side=tk.TOP, pady=(16, 2))
        self._dot_oval = self._dot_canvas.create_oval(1, 1, 11, 11,
                                                       fill=C["muted"], outline="")

        tk.Label(logo_frame, text="BH", fg=C["accent"], bg=C["surface"],
                 font=make_font(10, "bold")).pack(side=tk.TOP)

        # ── center: window picker ───────────────────────────────────
        center = tk.Frame(inner, bg=C["surface"])
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12)

        picker_row = tk.Frame(center, bg=C["surface"])
        picker_row.pack(fill=tk.X, pady=(12, 4))

        tk.Label(picker_row, text="Monitor window:", fg=C["muted"],
                 bg=C["surface"], font=make_font(9)).pack(side=tk.LEFT)

        refresh_btn = tk.Label(picker_row, text="↻", fg=C["accent"],
                               bg=C["surface"], font=make_font(12), cursor="hand2")
        refresh_btn.pack(side=tk.RIGHT, padx=(4, 0))
        refresh_btn.bind("<Button-1>", lambda e: self._refresh_windows())
        refresh_btn.bind("<Enter>", lambda e: refresh_btn.config(fg=C["accent_hov"]))
        refresh_btn.bind("<Leave>", lambda e: refresh_btn.config(fg=C["accent"]))

        self._window_var = tk.StringVar(value="— select a window —")
        self._window_menu = ttk.Combobox(
            center,
            textvariable=self._window_var,
            state="readonly",
            font=make_font(10),
            width=32,
        )
        self._window_menu.pack(fill=tk.X, pady=(0, 8))
        self._window_menu.bind("<<ComboboxSelected>>", self._on_window_selected)

        # ── right: controls + thumbnail ─────────────────────────────
        right = tk.Frame(inner, bg=C["surface"])
        right.pack(side=tk.RIGHT, padx=(4, 8))

        # Thumbnail
        self._thumb_canvas = tk.Canvas(right, width=self.THUMB_W,
                                        height=self.THUMB_H - 16,
                                        bg=C["panel"], highlightthickness=1,
                                        highlightbackground=C["border"])
        self._thumb_canvas.pack(side=tk.LEFT, padx=(0, 12))
        self._thumb_no_text = self._thumb_canvas.create_text(
            self.THUMB_W // 2, (self.THUMB_H - 16) // 2,
            text="No preview", fill=C["muted"], font=make_font(8), justify=tk.CENTER,
        )

        # Control buttons + timer
        ctrl = tk.Frame(right, bg=C["surface"])
        ctrl.pack(side=tk.LEFT)

        btn_row = tk.Frame(ctrl, bg=C["surface"])
        btn_row.pack(pady=(4, 4))

        self._btn_start = RoundedButton(
            btn_row, text="▶", bg_color=C["success"], fg_color=C["surface"],
            command=self._start_session, width=32, height=32, radius=16, font=make_font(11, "bold")
        )
        self._btn_start.pack(side=tk.LEFT, padx=3)

        self._btn_pause = RoundedButton(
            btn_row, text="⏸", bg_color=C["warning"], fg_color=C["surface"],
            command=self._pause_session, state=tk.DISABLED, width=32, height=32, radius=16, font=make_font(11, "bold")
        )
        self._btn_pause.pack(side=tk.LEFT, padx=3)

        self._btn_stop = RoundedButton(
            btn_row, text="⏹", bg_color=C["danger"], fg_color=C["surface"],
            command=self._stop_session, state=tk.DISABLED, width=32, height=32, radius=16, font=make_font(11, "bold")
        )
        self._btn_stop.pack(side=tk.LEFT, padx=3)

        # Settings gear
        gear = tk.Label(btn_row, text="⚙", fg=C["muted"], bg=C["surface"],
                        font=make_font(14), cursor="hand2")
        gear.pack(side=tk.LEFT, padx=(8, 0))
        gear.bind("<Button-1>", lambda e: self._open_settings())
        gear.bind("<Enter>", lambda e: gear.config(fg=C["text"]))
        gear.bind("<Leave>", lambda e: gear.config(fg=C["muted"]))

        # Timer label & status
        self._timer_lbl = tk.Label(ctrl, text="00:00:00",
                                    fg=C["muted"], bg=C["surface"],
                                    font=make_font(10, "bold"))
        self._timer_lbl.pack()

        self._status_lbl = tk.Label(ctrl, text="Select a window",
                                     fg=C["dim"], bg=C["surface"],
                                     font=make_font(8))
        self._status_lbl.pack()

        # ── close button (top-right corner on canvas) ────────────────
        close_btn = tk.Label(
            self._canvas, text="✕", fg=C["muted"],
            bg=C["surface"], font=make_font(10, "bold"), cursor="hand2",
        )
        close_btn.place(x=self.PILL_W - 24, y=8)
        close_btn.bind("<Button-1>", lambda e: self._on_close())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg=C["danger"]))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg=C["muted"]))

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
        self._timer_lbl.config(text="00:00:00", fg=C["muted"])

        # Clear thumbnail
        self._thumb_canvas.delete("all")
        self._thumb_no_text = self._thumb_canvas.create_text(
            self.THUMB_W // 2, (self.THUMB_H - 16) // 2,
            text="No preview", fill=C["muted"], font=make_font(8), justify=tk.CENTER,
        )

    def _update_btns(self, running: bool, paused: bool):
        if not running:
            self._btn_start.config_state(tk.NORMAL)
            self._btn_pause.config_state(tk.DISABLED)
            self._btn_stop.config_state(tk.DISABLED)
        elif paused:
            self._btn_start.config_state(tk.NORMAL)
            self._btn_pause.config_state(tk.NORMAL)
            self._btn_stop.config_state(tk.NORMAL)
        else:
            self._btn_start.config_state(tk.DISABLED)
            self._btn_pause.config_state(tk.NORMAL)
            self._btn_stop.config_state(tk.NORMAL)

    def _set_state(self, state: str):
        self._state = state
        self._canvas.itemconfig(self._pill_bg, outline=STATE_COLORS.get(state, STATE_COLORS["idle"]))

    def _set_status(self, msg: str):
        self._status_lbl.config(text=msg)

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
        
        inner = tk.Frame(set_canvas, bg=C["surface"])
        set_canvas.create_window(120, 90, window=inner, width=230, height=170)

        # Header
        hdr = tk.Frame(inner, bg=C["surface"])
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="⚙  Settings", fg=C["accent"],
                 bg=C["surface"], font=make_font(11, "bold"),
                 anchor="w", padx=12, pady=10).pack(side=tk.LEFT)
        close_set = tk.Label(hdr, text="✕", fg=C["muted"], bg=C["surface"], font=make_font(10), cursor="hand2")
        close_set.pack(side=tk.RIGHT, padx=12, pady=10)
        close_set.bind("<Button-1>", lambda e: win.destroy())
        close_set.bind("<Enter>", lambda e: close_set.config(fg=C["danger"]))
        close_set.bind("<Leave>", lambda e: close_set.config(fg=C["muted"]))
        
        tk.Frame(inner, bg=C["border"], height=1).pack(fill=tk.X)

        body = tk.Frame(inner, bg=C["surface"], padx=16, pady=14)
        body.pack(fill=tk.BOTH, expand=True)

        # Voice toggle
        tk.Checkbutton(
            body, text="Voice feedback",
            variable=self._voice_enabled,
            fg=C["text"], bg=C["surface"],
            selectcolor=C["panel"],
            activebackground=C["surface"],
            activeforeground=C["accent"],
            font=make_font(10),
            command=lambda: self.voice.set_enabled(self._voice_enabled.get()),
        ).pack(anchor="w", pady=4)

        # FPS slider
        fps_row = tk.Frame(body, bg=C["surface"])
        fps_row.pack(fill=tk.X, pady=(8, 0))
        tk.Label(fps_row, text="Capture FPS:", fg=C["muted"],
                 bg=C["surface"], font=make_font(9)).pack(side=tk.LEFT)
        self._settings_fps_lbl = tk.Label(fps_row, text=f"{self._fps_var.get():.1f}",
                                           fg=C["accent"], bg=C["surface"],
                                           font=make_font(10, "bold"))
        self._settings_fps_lbl.pack(side=tk.RIGHT)

        def _fps_upd(v):
            fps = round(float(v), 1)
            self._fps_var.set(fps)
            self.capture.fps = fps
            self._settings_fps_lbl.config(text=f"{fps:.1f}")

        ttk.Style().configure("Horizontal.TScale",
                              background=C["surface"], troughcolor=C["panel"])
        ttk.Scale(body, from_=0.2, to=5.0, orient=tk.HORIZONTAL,
                  variable=self._fps_var, length=200,
                  command=_fps_upd).pack(fill=tk.X, pady=(4, 0))

        # Refresh windows button
        tk.Button(
            body, text="↻  Refresh window list",
            fg=C["text"], bg=C["panel"],
            activeforeground=C["accent"],
            activebackground=C["panel"],
            relief="flat", cursor="hand2",
            font=make_font(9),
            command=self._refresh_windows,
        ).pack(fill=tk.X, pady=(16, 0))

    # ═══════════════════════════════════════════════════════════════════
    #   Frame processing
    # ═══════════════════════════════════════════════════════════════════

    def _on_frame(self, image: Image.Image):
        text = self.ocr.extract_text(image)
        insights = self.analyzer.analyze(text)
        self.root.after(0, lambda: self._update_ui(image, text, insights))

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
            self._timer_lbl.config(
                text=f"{h:02d}:{m:02d}:{s:02d}",
                fg=C["success"],
            )

        table = self._pulse_tables.get(self._state, self._pulse_tables["idle"])
        color = table[self._pulse_step % len(table)]
        self._dot_canvas.itemconfig(self._dot_oval, fill=color)
        if self._state != "idle":
            self._pulse_step += 1

        self.root.after(80, self._tick)

    # ═══════════════════════════════════════════════════════════════════
    #   Cleanup
    # ═══════════════════════════════════════════════════════════════════

    def _on_close(self):
        self.capture.stop()
        self.voice.stop()
        self.overlay.hide()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
