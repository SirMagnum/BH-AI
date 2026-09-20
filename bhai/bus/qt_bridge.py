"""
The only file allowed to import both `bhai.bus` and Qt.

Widgets never read the EventBus directly — they connect to
`QtEventBridge.event_received` and get called back on the Qt main thread.
This is what keeps "every widget mutation happens on the Qt main thread"
(roadmap §2.8) true without every widget needing to know it's consuming an
asyncio queue under a qasync loop.
"""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtCore import QObject, Signal

from bhai.bus.bus import EventBus
from bhai.bus.events import BusEvent

logger = logging.getLogger(__name__)


class QtEventBridge(QObject):
    """Pumps EventBus events onto a Qt signal.

    Requires a qasync event loop to already be running (i.e. the app was
    started via qasync.QEventLoop), since it schedules an asyncio task.
    """

    event_received = Signal(object)  # emits BusEvent instances

    def __init__(self, bus: EventBus, topic: str | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._bus = bus
        self._subscription = bus.subscribe(topic)
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.ensure_future(self._pump())

    def stop(self) -> None:
        self._subscription.close()
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _pump(self) -> None:
        try:
            async for event in self._subscription:
                self.event_received.emit(event)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001 — a bridge crash must never be silent
            logger.exception("QtEventBridge pump crashed")


def publish(bus: EventBus, event: BusEvent) -> None:
    """Thin wrapper kept for call-site clarity; publish is otherwise sync."""
    bus.publish(event)
