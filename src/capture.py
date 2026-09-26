"""
Screen Capture Module for BH-AI.
Governed by the Deterministic Finite Automaton (StateMachine).
Guarantees physical OS capture handle disposal during PAUSED and DORMANT states,
and provides an inactivity watchdog to auto-transition on idle timeout.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable
import mss
import mss.tools
from PIL import Image

from src.state_machine import StateMachine, State, Trigger

logger = logging.getLogger("BH-AI.ScreenCapture")


class ScreenCapture:
    """
    Captures a user-defined screen region at a set interval.
    Tightly bound to DFA StateMachine:
      - ACTIVE: OS capture handle open, continuous grabbing.
      - PAUSED: OS capture handle explicitly disposed (zero observation).
      - DORMANT: Capture loop terminated, OS handles released.
    """

    def __init__(
        self,
        region: dict | None = None,
        fps: float = 1.0,
        state_machine: StateMachine | None = None,
        idle_timeout_seconds: float | None = 300.0,
    ):
        """
        :param region: dict with keys left, top, width, height (screen coords)
        :param fps: captures per second
        :param state_machine: StateMachine instance (or created by default)
        :param idle_timeout_seconds: Inactivity timeout in seconds, or None to disable.
        """
        self.region = region  # {"left": x, "top": y, "width": w, "height": h}
        self.fps = fps
        self.state_machine = state_machine or StateMachine()
        self.idle_timeout_seconds = idle_timeout_seconds

        self._lock = threading.RLock()
        self._sct: mss.mss | None = None
        self._latest_frame: Image.Image | None = None
        self._on_frame_callback: Callable[[Image.Image], None] | None = None

        self._thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._wake_event = threading.Event()
        self._last_activity_time = time.time()

        # Bind to state transitions
        self.state_machine.add_listener(self._on_state_changed)

    # ------------------------------------------------------------------ #
    #  Public Configuration & Callbacks
    # ------------------------------------------------------------------ #

    def set_region(self, x: int, y: int, width: int, height: int) -> None:
        """Update region coordinates."""
        with self._lock:
            self.region = {"left": x, "top": y, "width": width, "height": height}
            self.touch_activity()

    def set_callback(self, fn: Callable[[Image.Image], None] | None) -> None:
        """Register a callback that receives each captured PIL.Image frame."""
        with self._lock:
            self._on_frame_callback = fn

    def touch_activity(self) -> None:
        """Reset the inactivity watchdog timer."""
        with self._lock:
            self._last_activity_time = time.time()

    # ------------------------------------------------------------------ #
    #  State Machine Driven Controls
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Initiate capture by transitioning state machine to ACTIVE."""
        if self.state_machine.is_dormant:
            self.state_machine.trigger(Trigger.START)

        self._ensure_threads_running()
        self.touch_activity()
        self._wake_event.set()

    def pause(self) -> None:
        """Pause capture by transitioning state machine to PAUSED."""
        if self.state_machine.can_trigger(Trigger.PAUSE):
            self.state_machine.trigger(Trigger.PAUSE)

    def resume(self) -> None:
        """Resume capture by transitioning state machine to ACTIVE."""
        if self.state_machine.can_trigger(Trigger.RESUME):
            self.state_machine.trigger(Trigger.RESUME)

        self._ensure_threads_running()
        self.touch_activity()
        self._wake_event.set()

    def stop(self) -> None:
        """Stop capture completely by transitioning state machine to DORMANT."""
        if not self.state_machine.is_dormant:
            self.state_machine.trigger(Trigger.STOP)

        self._wake_event.set()
        self._dispose_handles()
        with self._lock:
            self._latest_frame = None

    # ------------------------------------------------------------------ #
    #  State Inspection & Backward Compatibility
    # ------------------------------------------------------------------ #

    @property
    def is_running(self) -> bool:
        """True only if state machine is actively in ACTIVE state."""
        return self.state_machine.is_active

    @property
    def is_paused(self) -> bool:
        """True if state machine is PAUSED."""
        return self.state_machine.is_paused

    @property
    def latest_frame(self) -> Image.Image | None:
        """Get the most recent frame."""
        with self._lock:
            return self._latest_frame

    @property
    def has_active_handle(self) -> bool:
        """Verify whether physical OS capture handle (mss) is allocated."""
        with self._lock:
            return self._sct is not None

    # ------------------------------------------------------------------ #
    #  Internal OS Handle Management
    # ------------------------------------------------------------------ #

    def _acquire_handles(self) -> None:
        """Instantiate screen capture handle."""
        with self._lock:
            if self._sct is None:
                self._sct = mss.mss()
                logger.debug("[Capture] OS capture handle allocated.")

    def _dispose_handles(self) -> None:
        """Explicitly release and close OS screen capture handles."""
        with self._lock:
            if self._sct is not None:
                try:
                    self._sct.close()
                except Exception as exc:
                    logger.debug(f"[Capture] Error while closing mss handle: {exc}")
                finally:
                    self._sct = None
                    logger.debug("[Capture] OS capture handle disposed.")

    def _on_state_changed(
        self,
        source: State,
        target: State,
        trigger: Trigger,
        payload: Any = None,
    ) -> None:
        """React directly to state changes from state machine."""
        if target in (State.PAUSED, State.DORMANT):
            self._dispose_handles()

        if target == State.ACTIVE:
            self._wake_event.set()

    # ------------------------------------------------------------------ #
    #  Thread Management & Capture Loop
    # ------------------------------------------------------------------ #

    def _ensure_threads_running(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="CaptureLoop")
                self._thread.start()

            if (self.idle_timeout_seconds and self.idle_timeout_seconds > 0) and (
                self._watchdog_thread is None or not self._watchdog_thread.is_alive()
            ):
                self._watchdog_thread = threading.Thread(
                    target=self._watchdog_loop, daemon=True, name="InactivityWatchdog"
                )
                self._watchdog_thread.start()

    def _capture_loop(self) -> None:
        """Worker thread executing periodic screen grab when ACTIVE."""
        while not self.state_machine.is_dormant:
            if self.state_machine.is_paused or self.region is None:
                self._dispose_handles()
                self._wake_event.wait(timeout=0.2)
                self._wake_event.clear()
                continue

            if self.state_machine.is_active:
                interval = 1.0 / max(self.fps, 0.1)
                try:
                    if self._sct is None:
                        self._acquire_handles()

                    with self._lock:
                        region = self.region.copy()

                    raw = self._sct.grab(region)
                    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

                    with self._lock:
                        self._latest_frame = img

                    if self._on_frame_callback:
                        self._on_frame_callback(img.copy())

                except Exception as exc:
                    logger.error(f"[Capture] Frame acquisition error: {exc}")

                time.sleep(interval)
            else:
                self._wake_event.wait(timeout=0.2)
                self._wake_event.clear()

        self._dispose_handles()

    def _watchdog_loop(self) -> None:
        """Monitors inactivity and triggers TIMEOUT when idle limit reached."""
        while not self.state_machine.is_dormant:
            time.sleep(0.5)

            if self.idle_timeout_seconds and self.idle_timeout_seconds > 0:
                with self._lock:
                    idle_duration = time.time() - self._last_activity_time

                if idle_duration >= self.idle_timeout_seconds:
                    if self.state_machine.can_trigger(Trigger.TIMEOUT):
                        logger.info(
                            f"[Capture] Idle limit reached ({idle_duration:.1f}s >= {self.idle_timeout_seconds}s). Triggering TIMEOUT."
                        )
                        self.state_machine.trigger(Trigger.TIMEOUT)
                        self._dispose_handles()
                        self._wake_event.set()
                        break
