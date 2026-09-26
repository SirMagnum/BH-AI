"""
Wake-Word Detection & Global Push-To-Talk (PTT) Module for BH-AI.
Enables hands-free voice query activation ("Hey Assistant") and OS-level global hotkey triggers.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import re
import threading
import time
from typing import Any, Callable

from src.state_machine import StateMachine, State, Trigger

logger = logging.getLogger("BH-AI.WakeWord")


# ------------------------------------------------------------------ #
#  Wake-Word Spotter
# ------------------------------------------------------------------ #

class WakeWordDetector:
    """
    Keyword spotter for local hands-free activation.
    Matches audio chunks or transcribed text against configured wake phrases.
    """

    DEFAULT_WAKE_PHRASES = [
        "hey assistant",
        "assistant",
        "hey bhai",
        "bhai",
    ]

    def __init__(
        self,
        wake_phrases: list[str] | None = None,
        on_wake: Callable[[], None] | None = None,
    ):
        self.wake_phrases = [
            p.lower().strip() for p in (wake_phrases or self.DEFAULT_WAKE_PHRASES)
        ]
        self.on_wake = on_wake
        self._lock = threading.RLock()

    def check_phrase(self, text: str) -> bool:
        """
        Check if text transcript contains any configured wake phrase.
        Returns True if matched, and invokes on_wake callback.
        """
        if not text:
            return False

        lower = text.lower().strip()
        for phrase in self.wake_phrases:
            # Word boundary search
            if re.search(r"\b" + re.escape(phrase) + r"\b", lower) or phrase in lower:
                logger.info(f"[WakeWord] Wake phrase '{phrase}' detected!")
                if self.on_wake:
                    try:
                        self.on_wake()
                    except Exception as exc:
                        logger.error(f"[WakeWord] Error in wake callback: {exc}")
                return True
        return False

    def process_audio_frame(self, frame_bytes: bytes, threshold_rms: float = 500.0) -> bool:
        """
        Energy and acoustic activity gate on incoming PCM audio bytes.
        """
        if not frame_bytes or len(frame_bytes) < 2:
            return False

        import numpy as np
        samples = np.frombuffer(frame_bytes, dtype=np.int16)
        if len(samples) == 0:
            return False
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
        return rms >= threshold_rms


# ------------------------------------------------------------------ #
#  Push-To-Talk (Global Hotkey Manager)
# ------------------------------------------------------------------ #

# Windows Hotkey Modifier Constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
VK_SPACE = 0x20


class PushToTalkManager:
    """
    Global Push-To-Talk (PTT) manager using native Windows RegisterHotKey.
    Runs a lightweight message loop in a daemon thread.
    """

    def __init__(
        self,
        on_hotkey: Callable[[], None] | None = None,
        modifiers: int = MOD_CONTROL | MOD_SHIFT,
        vk: int = VK_SPACE,
    ):
        self.on_hotkey = on_hotkey
        self.modifiers = modifiers | MOD_NOREPEAT
        self.vk = vk

        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._hotkey_id = 101

    def start(self) -> None:
        """Start global hotkey listener thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._msg_loop, daemon=True, name="PushToTalkListener"
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop global hotkey listener thread."""
        with self._lock:
            self._running = False
            # Post WM_QUIT to unblock GetMessage
            try:
                if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "user32"):
                    thread_id = self._thread.ident if self._thread else None
                    if thread_id:
                        ctypes.windll.user32.PostThreadMessageW(thread_id, 0x0012, 0, 0)
            except Exception:
                pass
            self._thread = None

    def simulate_hotkey_press(self) -> None:
        """Simulate hotkey press programmatically for testing / headless environments."""
        if self.on_hotkey:
            try:
                self.on_hotkey()
            except Exception as exc:
                logger.error(f"[PTT] Error in hotkey callback: {exc}")

    def _msg_loop(self) -> None:
        """Windows message pump for RegisterHotKey."""
        user32 = getattr(ctypes.windll, "user32", None)
        if not user32:
            return

        # Register hotkey
        success = user32.RegisterHotKey(None, self._hotkey_id, self.modifiers, self.vk)
        if not success:
            logger.warning("[PTT] Failed to register global hotkey. Key may already be in use.")
            return

        logger.info("[PTT] Global Push-To-Talk hotkey registered.")
        msg = ctypes.wintypes.MSG()

        try:
            while self._running:
                # PeekMessage with timeout or GetMessage
                res = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)  # PM_REMOVE = 1
                if res != 0:
                    if msg.message == 0x0312:  # WM_HOTKEY
                        logger.info("[PTT] Global Push-To-Talk hotkey activated!")
                        self.simulate_hotkey_press()
                    elif msg.message == 0x0012:  # WM_QUIT
                        break
                time.sleep(0.05)
        finally:
            user32.UnregisterHotKey(None, self._hotkey_id)
            logger.info("[PTT] Global Push-To-Talk hotkey unregistered.")


# ------------------------------------------------------------------ #
#  Combined Voice Trigger Controller
# ------------------------------------------------------------------ #

class VoiceTriggerController:
    """
    Coordinates wake-word detection and Push-To-Talk hotkey activations.
    Optionally binds to StateMachine to resume or notify on voice triggers.
    """

    def __init__(
        self,
        state_machine: StateMachine | None = None,
        on_trigger: Callable[[str], None] | None = None,
    ):
        self.state_machine = state_machine
        self.on_trigger = on_trigger

        self.wakeword = WakeWordDetector(on_wake=lambda: self._handle_activation("wakeword"))
        self.ptt = PushToTalkManager(on_hotkey=lambda: self._handle_activation("hotkey"))

    def start(self) -> None:
        """Start listening for Push-To-Talk hotkey."""
        self.ptt.start()

    def stop(self) -> None:
        """Stop listening for hotkeys."""
        self.ptt.stop()

    def _handle_activation(self, trigger_type: str) -> None:
        logger.info(f"[VoiceTrigger] Voice interaction activated via {trigger_type}.")

        # If system is paused and trigger is received, we can resume observation
        if self.state_machine and self.state_machine.is_paused:
            if self.state_machine.can_trigger(Trigger.RESUME):
                self.state_machine.trigger(Trigger.RESUME)

        if self.on_trigger:
            try:
                self.on_trigger(trigger_type)
            except Exception as exc:
                logger.error(f"[VoiceTrigger] Error in activation handler: {exc}")
