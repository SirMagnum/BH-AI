"""
Domain and Application Blocklist Engine for BH-AI.
Monitors foreground window titles and application executables.
Triggers immediate deterministic hard-pauses (BLOCK_MATCH -> PAUSED)
when sensitive applications (password managers, banking, private chats) are detected.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from src.state_machine import StateMachine, State, Trigger

logger = logging.getLogger("BH-AI.Blocklist")


@dataclass(frozen=True)
class BlocklistMatch:
    """Detailed record of a blocklist match event."""
    matched: bool
    reason: str             # "app" | "title"
    pattern: str
    window_title: str
    app_name: str


class BlocklistConfig:
    """
    Configurable rules for sensitive application and window title blocking.
    """

    DEFAULT_BLOCKED_APPS = {
        # Password Managers & Vaults
        "1password",
        "bitwarden",
        "keepass",
        "keepassxc",
        "lastpass",
        "dashlane",
        "enpass",
        "nordpass",
        "roboform",
        # Private Messaging & Sensitive Comms
        "signal",
        "telegram",
        "whatsapp",
        "tor",
        "protonmail",
        # Crypto & Wallets
        "metamask",
        "ledger live",
        "exodus",
        "electrum",
        "trezor suite",
        # Financial & Tax
        "turbotax",
        "quicken",
    }

    DEFAULT_BLOCKED_TITLE_KEYWORDS = {
        "login",
        "log in",
        "sign in",
        "signin",
        "password",
        "passwords",
        "credentials",
        "master password",
        "authenticator",
        "two-factor",
        "2fa",
        "banking",
        "bank of america",
        "chase online",
        "wells fargo",
        "citibank",
        "paypal checkout",
        "payment method",
        "credit card",
        "crypto wallet",
    }

    def __init__(
        self,
        blocked_apps: set[str] | None = None,
        blocked_titles: set[str] | None = None,
    ):
        self.blocked_apps: set[str] = (
            set(blocked_apps) if blocked_apps is not None else set(self.DEFAULT_BLOCKED_APPS)
        )
        self.blocked_titles: set[str] = (
            set(blocked_titles) if blocked_titles is not None else set(self.DEFAULT_BLOCKED_TITLE_KEYWORDS)
        )
        self._lock = threading.RLock()

    def add_app(self, app_name: str) -> None:
        with self._lock:
            self.blocked_apps.add(app_name.lower().strip())

    def remove_app(self, app_name: str) -> None:
        with self._lock:
            self.blocked_apps.discard(app_name.lower().strip())

    def add_title_pattern(self, pattern: str) -> None:
        with self._lock:
            self.blocked_titles.add(pattern.lower().strip())

    def remove_title_pattern(self, pattern: str) -> None:
        with self._lock:
            self.blocked_titles.discard(pattern.lower().strip())

    def is_match(self, window_title: str, app_name: str = "") -> BlocklistMatch | None:
        """
        Check if window title or app executable matches any blocklist rule.
        Returns BlocklistMatch if matched, None otherwise.
        """
        title_lower = (window_title or "").lower()
        app_lower = (app_name or "").lower()

        with self._lock:
            # Check executable/app name
            if app_lower:
                for blocked_app in self.blocked_apps:
                    if blocked_app in app_lower:
                        return BlocklistMatch(
                            matched=True,
                            reason="app",
                            pattern=blocked_app,
                            window_title=window_title,
                            app_name=app_name,
                        )

            # Check window title keywords
            if title_lower:
                for pattern in self.blocked_titles:
                    # Match pattern as substring or word boundary
                    if re.search(r"\b" + re.escape(pattern) + r"\b", title_lower) or pattern in title_lower:
                        return BlocklistMatch(
                            matched=True,
                            reason="title",
                            pattern=pattern,
                            window_title=window_title,
                            app_name=app_name,
                        )

        return None


# ------------------------------------------------------------------ #
#  Foreground Window Inspection Helper
# ------------------------------------------------------------------ #

def get_foreground_window_info() -> tuple[str, str]:
    """
    Retrieve the current active foreground window's title and process executable name.
    Safe across all Windows platforms with fallback handling.
    """
    title = ""
    app_name = ""

    try:
        import win32gui
        import win32process
        import psutil

        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            title = win32gui.GetWindowText(hwnd) or ""
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid:
                try:
                    proc = psutil.Process(pid)
                    app_name = proc.name() or ""
                except Exception:
                    app_name = ""
    except Exception as exc:
        logger.debug(f"[Blocklist] Could not inspect foreground window: {exc}")

    return title.strip(), app_name.strip()


# ------------------------------------------------------------------ #
#  Window Blocklist Watchdog Monitor
# ------------------------------------------------------------------ #

class WindowBlocklistMonitor:
    """
    Continuous background monitor that observes active foreground windows.
    Automatically fires Trigger.BLOCK_MATCH on StateMachine to force an
    immediate privacy hard-pause whenever a sensitive application is focused.
    """

    def __init__(
        self,
        state_machine: StateMachine,
        config: BlocklistConfig | None = None,
        poll_interval: float = 0.5,
        window_inspector: Callable[[], tuple[str, str]] | None = None,
    ):
        self.state_machine = state_machine
        self.config = config or BlocklistConfig()
        self.poll_interval = max(poll_interval, 0.1)
        self._window_inspector = window_inspector or get_foreground_window_info

        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def start(self) -> None:
        """Start the background watchdog thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._poll_loop, daemon=True, name="BlocklistWatchdog"
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop the background watchdog."""
        with self._lock:
            self._running = False
            self._thread = None

    def check_now(self) -> BlocklistMatch | None:
        """
        Inspect current active window immediately.
        If matched and state machine is ACTIVE, fires BLOCK_MATCH trigger.
        Returns BlocklistMatch or None.
        """
        title, app_name = self._window_inspector()
        match = self.config.is_match(title, app_name)

        if match:
            if self.state_machine.is_active:
                logger.warning(
                    f"[Blocklist] Sensitive window detected! ({match.reason}='{match.pattern}'). "
                    f"Triggering BLOCK_MATCH hard-pause."
                )
                self.state_machine.trigger(
                    Trigger.BLOCK_MATCH,
                    payload={
                        "window": match.window_title,
                        "app": match.app_name,
                        "pattern": match.pattern,
                        "reason": match.reason,
                    },
                )
        return match

    def _poll_loop(self) -> None:
        """Worker loop checking foreground window periodically."""
        while self._running:
            try:
                if self.state_machine.is_active:
                    self.check_now()
            except Exception as exc:
                logger.error(f"[Blocklist] Error in monitor loop: {exc}")

            time.sleep(self.poll_interval)
