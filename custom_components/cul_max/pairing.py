"""Runtime-only results for one controller's most recent pairing window."""
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


@dataclass
class PairingSession:
    id: str | None = None
    started_at: str | None = None
    ends_at: str | None = None
    active: bool = False
    devices: dict = field(default_factory=dict)
    rejected: dict = field(default_factory=dict)
    error: str | None = None
    initial_known: dict[str, bool] = field(default_factory=dict)

    def start(self, until):
        self.id = str(uuid4())
        self.started_at = datetime.now(UTC).isoformat()
        self.ends_at = until.isoformat()
        self.active = True
        self.devices.clear()
        self.rejected.clear()
        self.initial_known.clear()
        self.error = None

    def observe(self, session_id: str | None, address: str, known: bool) -> bool:
        """Freeze identity before asynchronous pair replies or device creation."""
        if session_id is not None and session_id == self.id:
            return self.initial_known.setdefault(address, known)
        return known

    def record(self, session_id, address, known):
        if session_id is not None and session_id == self.id:
            self.rejected.pop(address, None)
            self.devices.setdefault(address, {"address": address, "already_known": known})

    def reject(self, session_id, address, partner_address):
        """Retain the latest foreign partner only for the active window."""
        if self.active and session_id is not None and session_id == self.id:
            self.rejected[address] = {
                "address": address, "partner_address": partner_address,
            }
