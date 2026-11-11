"""Synchronous thermostat reconciliation; no transport, timers or persistence."""
from __future__ import annotations

from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .coordinator import KnownDevice, TemperatureIntent

from .const import MODE_AUTO, MODE_BOOST, MODE_MANUAL, MODE_VACATION, MODE_NAMES, TEMP_MIN


class ClimateStateModel:
    """View over device knowledge and one request, without copying state."""

    def __init__(self, device: KnownDevice | None, intent: TemperatureIntent | None):
        self.device = device
        self.intent = intent

    def matches_report(self) -> bool:
        intent = self.intent
        if intent is None:
            return False
        reported = self.device.last_state if self.device else {}
        required = {"mode"}
        if not (intent.mode in (MODE_AUTO, MODE_BOOST) and intent.temperature <= 0):
            required.add("desired_temperature")
        if intent.until is not None:
            required.add("until")
        return (
            required <= intent.reported_fields
            and reported.get("mode") == intent.mode
            and ("desired_temperature" not in required
                 or reported.get("desired_temperature") == intent.display_temperature)
            and ("until" not in required
                 or reported.get("until") == intent.until.astimezone().strftime("%Y-%m-%d %H:%M"))
        )

    def report_received(self, fields: set[str]) -> None:
        """Reconcile only fields received after this intent's TCP handoff.

        Receive order is the only available order for unsolicited state. Never
        change the display merely because time passed, or trigger an RF retry.
        """
        intent = self.intent
        if intent and intent.entry.may_have_transmitted:
            intent.reported_fields.update(fields)
            if self.matches_report() and intent.command_status in {"acknowledged", "unconfirmed"}:
                intent.command_status = "synchronized"

    def acknowledge(self) -> None:
        """Keep accepted settings separately from actual reports, without a timer.

        Even a predecessor's ACK updates the fallback for a newer pending wish.
        No reported values are fabricated or persisted from command acceptance.
        """
        intent = self.intent
        device = self.device
        if device is None:
            return
        if intent.mode in (MODE_AUTO, MODE_BOOST) and intent.temperature <= 0:
            device.acknowledged_state.pop("desired_temperature", None)
        if self.matches_report():
            intent.command_status = "synchronized"
        else:
            intent.command_status = "acknowledged"
            accepted = {"mode": intent.mode,
                        "until": intent.until.astimezone().strftime("%Y-%m-%d %H:%M") if intent.until else None}
            if not (intent.mode in (MODE_AUTO, MODE_BOOST) and intent.temperature <= 0):
                accepted["desired_temperature"] = intent.display_temperature
            device.acknowledged_state.update(accepted)
            intent.reported_fields.clear()
        if intent.display_temperature is not None and intent.temperature > TEMP_MIN:
            device.last_normal_target = intent.display_temperature

    def update_outcome(self) -> None:
        """Queue status owns progress; only terminal outcomes need display detail."""
        intent = self.intent
        if intent.command_status is not None:
            return
        status = intent.entry.status
        if status not in {"completed", "failed", "cancelled", "superseded"}:
            return
        if status == "completed":
            intent.command_status = "acknowledged"
        elif intent.entry.may_have_transmitted and not intent.entry.delivery_rejected:
            intent.command_status = "unconfirmed"
        else:
            intent.command_status = status
            return
        if self.matches_report():
            intent.command_status = "synchronized"

    def display(self) -> dict[str, Any]:
        """Project reported state plus the latest complete user intent, without I/O."""
        device = self.device
        reported = device.last_state if device else {}
        accepted = device.acknowledged_state if device else {}
        effective = {**reported, **accepted}
        intent = self.intent
        desired = intent if intent and intent.overlay else None
        mode = desired.mode if desired else effective.get("mode")
        target = desired.display_temperature if desired else effective.get("desired_temperature")
        preset = {MODE_BOOST: "boost", MODE_VACATION: "away"}.get(mode, "none")
        hvac = {MODE_AUTO: "auto", MODE_MANUAL: "heat", MODE_BOOST: "heat",
                MODE_VACATION: "heat"}.get(mode)
        if mode == MODE_MANUAL and target == TEMP_MIN:
            hvac = "off"
        until = desired.until if desired else None
        if desired is None and effective.get("until"):
            try:
                until = datetime.fromisoformat(effective["until"]).astimezone()
            except (ValueError, TypeError):
                pass
        return {
            "target_temperature": target, "current_temperature": reported.get("measured_temperature"),
            "mode": mode, "hvac_mode": hvac, "preset_mode": preset, "hvac_action": None,
            "until": until, "reported": dict(reported),
            "requested_target_temperature": desired.display_temperature if desired else None,
            "requested_mode": MODE_NAMES.get(desired.mode) if desired else None,
            "reported_target_temperature": reported.get("desired_temperature"),
            "reported_mode": MODE_NAMES.get(reported.get("mode")),
            "command_status": (intent.command_status or intent.entry.status) if intent else
                              "synchronized" if mode is not None else None,
            "state_source": "requested" if desired else "acknowledged" if accepted else "reported",
        }

