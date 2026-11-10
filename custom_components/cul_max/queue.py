"""Inspectable command admission, replacement and cancellation (no transport I/O)."""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable
from types import MappingProxyType
from uuid import uuid4

_LOGGER = logging.getLogger(__name__)

TERMINAL = frozenset({"completed", "failed", "cancelled", "superseded"})


@dataclass(frozen=True)
class CommandResult:
    status: str
    ack: Any = None

    @property
    def counter(self):
        """Retain convenience access for internal ACK consumers."""
        return self.ack.counter if self.ack is not None else None


class QueueStopped(Exception):
    """Expected control flow, never a communication failure."""

    def __init__(self, status: str):
        self.status = status
        super().__init__(status)


@dataclass
class QueueEntry:
    device_address: str | None
    device_name: str
    command_type: str
    description: str
    future: asyncio.Future
    payload: Any = None
    replace_key: str | None = None
    priority: bool = False
    scope: str = "general"
    job_id: str | None = None
    protected: bool = False
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: str = "queued"
    attempts: int = 0
    last_error: str | None = None
    has_been_sent: bool = False
    stop: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def cancellable(self) -> bool:
        return not self.has_been_sent and not self.protected and self.status not in TERMINAL

    def snapshot(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in (
            "id", "device_address", "device_name", "command_type", "description",
            "created_at", "status", "replace_key", "priority", "scope", "job_id",
            "attempts", "last_error",
        )} | {"cancellable": self.cancellable, "has_been_sent": self.has_been_sent,
             "blocked_reason": "Bereits übergeben" if self.has_been_sent else
             "Teil eines Konfigurationsablaufs oder einer Protokollantwort" if self.protected else None}


class CommandQueueManager:
    """All mutations are synchronous on HA's event loop; no private Queue access."""

    def __init__(self, changed: Callable[[], None], capacity: int = 256):
        self._entries: OrderedDict[str, QueueEntry] = OrderedDict()
        self.history: deque[dict] = deque(maxlen=50)
        self._pending: OrderedDict[str, QueueEntry] = OrderedDict()
        self._ready = asyncio.Event()
        self.changed = changed
        self.capacity = capacity
        self.superseded_count = 0
        self.cancelled_count = 0
        self.last_error: str | None = None
        self.revision = 0
        self.session_id = str(uuid4())

    @property
    def entries(self):
        """Read-only index; mutations go through the queue API."""
        return MappingProxyType(self._entries)

    def notify(self) -> None:
        self.revision += 1
        self.changed()

    def add(self, entry: QueueEntry, *, worker: bool = True) -> None:
        if entry.replace_key:
            for old in list(self._entries.values()):
                if old.replace_key == entry.replace_key and old.cancellable:
                    _LOGGER.debug("Queue: Replaced %s → %s", old.description, entry.description)
                    self.finish(old, "superseded")
        if len(self._entries) >= self.capacity:
            self.last_error = "Sendewarteschlange ist voll"
            self.notify()
            raise ValueError(self.last_error)
        self._entries[entry.id] = entry
        if worker:
            self._pending[entry.id] = entry
            self._ready.set()
        self.notify()

    async def get(self):
        while not self._pending:
            self._ready.clear()
            await self._ready.wait()
        _, entry = self._pending.popitem(last=False)
        return entry.payload

    def qsize(self) -> int:
        return len(self._pending)

    def empty(self) -> bool:
        return not self._pending

    def get_nowait(self):
        if not self._pending:
            raise asyncio.QueueEmpty
        return self._pending.popitem(last=False)[1].payload

    def task_done(self) -> None:
        """Worker compatibility; completion is recorded with finish()."""

    def set_status(self, entry: QueueEntry, status: str) -> None:
        if entry.status not in TERMINAL and entry.status != status:
            entry.status = status
            self.notify()

    def before_write(self, entry: QueueEntry) -> None:
        if entry.status in TERMINAL:
            raise QueueStopped(entry.status)
        entry.has_been_sent = True
        entry.attempts += 1
        self.set_status(entry, "sending")

    def finish(self, entry: QueueEntry, status: str, *, ack=None, error=None) -> None:
        if entry.status in TERMINAL:
            return
        entry.status = status
        _LOGGER.debug("Queue: %s %s (%s)", status, entry.description, entry.id)
        entry.last_error = str(error) if error else entry.last_error
        if status == "superseded":
            self.superseded_count += 1
        if status == "cancelled":
            self.cancelled_count += 1
        if error:
            self.last_error = str(error)
        self._pending.pop(entry.id, None)
        self._entries.pop(entry.id, None)
        self.history.append(entry.snapshot())
        if status in {"cancelled", "superseded"}:
            entry.stop.set()
        if not entry.future.done():
            if error:
                entry.future.set_exception(error)
            else:
                entry.future.set_result(CommandResult(status, ack))
        self.notify()

    def delete(self, entry_id: str) -> None:
        entry = self._entries.get(entry_id)
        if entry is None:
            raise ValueError("Queue-Eintrag nicht mehr vorhanden")
        if not entry.cancellable:
            raise ValueError("Queue-Eintrag ist nicht abbrechbar")
        self.finish(entry, "cancelled")

    def clear(self, address: str | None = None) -> dict:
        removed, protected = [], []
        for entry in list(self._entries.values()):
            if entry.scope != "general" or (address and entry.device_address != address.upper()):
                continue
            if entry.cancellable:
                self.finish(entry, "cancelled")
                removed.append(entry.id)
            else:
                protected.append(entry.id)
        return {"removed": removed, "protected": protected}

    def snapshot(self) -> dict:
        entries = [entry.snapshot() for entry in self._entries.values()]
        return {
            "session_id": self.session_id, "revision": self.revision, "entries": entries,
            "history": [dict(item) for item in self.history], "superseded_count": self.superseded_count,
            "cancelled_count": self.cancelled_count, "last_error": self.last_error,
            "waiting": sum(e["status"] in {"queued", "waiting_for_credits"} for e in entries),
            "active": sum(e["status"] in {"sending", "awaiting_ack", "retrying"} for e in entries),
        }
