"""Room configuration snapshots and durable admission; transport stays in the coordinator."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from uuid import uuid4

from .const import CLIMATE_DEVICE_TYPES, DOMAIN
from .protocol import (encode_week_profile, format_week_profile_by_day, parse_max_temperature,
                       parse_week_profile_text, split_week_profile_for_send)

TEMPERATURE_KEYS = ("comfort_temperature", "eco_temperature", "window_open_temperature", "window_open_duration")
CONFIG_KEYS = (*TEMPERATURE_KEYS, "measurement_offset")
DAY_LABELS = {"monday": "Mon", "tuesday": "Tue", "wednesday": "Wed", "thursday": "Thu",
              "friday": "Fri", "saturday": "Sat", "sunday": "Sun"}
DAY_INDEX = {key: (index + 2) % 7 for index, key in enumerate(DAY_LABELS)}
TERMINAL = {"completed", "cancelled", "failed"}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def registry_members(hass, controllers) -> list[dict]:
    """Honor entity area overrides; never infer rooms from names or RF groups."""
    from homeassistant.helpers import area_registry, device_registry, entity_registry
    areas = area_registry.async_get(hass)
    devices = device_registry.async_get(hass)
    entities = entity_registry.async_get(hass)
    result = []
    for entity in entities.entities.values():
        if entity.platform != DOMAIN or entity.domain != "climate":
            continue
        coordinator = controllers.get(entity.config_entry_id)
        if coordinator is None:
            continue
        device_entry = devices.async_get(entity.device_id) if entity.device_id else None
        area_id = entity.area_id or (device_entry.area_id if device_entry else None)
        area = areas.async_get_area(area_id) if area_id else None
        if area is None:
            continue
        for device in coordinator.get_all_devices():
            if (entity.unique_id == f"{DOMAIN}_{device.address}" and device.device_type in CLIMATE_DEVICE_TYPES
                    and not device.superseded_by):
                result.append({"area_id": area.id, "area_name": area.name,
                               "config_entry_id": entity.config_entry_id, "address": device.address})
    return result


def device_snapshot(coordinator, address: str) -> dict:
    device = coordinator.get_device(address)
    coordinator._ensure_config_jobs()
    by_day = format_week_profile_by_day(device.week_profile) if device.week_profile else {}
    confirmed = {key: getattr(device, key) for key in TEMPERATURE_KEYS}
    confirmed["week_profile"] = {key: by_day.get(key) if device.week_profile_known_days is None
                                 or DAY_INDEX[key] in device.week_profile_known_days else None
                                 for key in DAY_LABELS}
    values = deepcopy(confirmed)
    locks = {block: coordinator.config_busy(address, block) for block in ("temperature", "week_profile")}
    commands = coordinator._pending_climate_config.get(address, [])
    for command in commands:
        if command.op == "config_temperatures":
            values.update({key: value for key, value in command.temperature_config.items() if key in TEMPERATURE_KEYS})
        elif command.profile_hex:
            days = format_week_profile_by_day(command.profile_hex)
            key = next(key for key, index in DAY_INDEX.items() if index == command.day)
            values["week_profile"][key] = days[key]
    draft = coordinator.get_config_draft(address)
    for key in TEMPERATURE_KEYS:
        if key in draft and not locks["temperature"]:
            values[key] = draft[key]
    dirty_days = draft.get("week_profile_dirty_days", [])
    for key in dirty_days if not locks["week_profile"] else []:
        values["week_profile"][key] = draft["week_profile_by_day"][key]
    queue = coordinator.get_queue()
    jobs = [deepcopy(job) for job in queue["jobs"]
            if job["device_address"] == address and job["kind"] == "climate"]
    for entry in queue["entries"]:
        if entry["device_address"] != address or entry["job_id"] or not entry["command_type"].startswith(("ConfigTemperatures", "ConfigWeekProfile")):
            continue
        jobs.append({"id": entry["id"], "block": "temperature" if entry["command_type"].startswith("ConfigTemperatures") else "week_profile",
                     "kind": "climate", "status": entry["status"], "description": entry["description"],
                     "direct": True, "steps": [{"id": entry["id"]}], "confirmed_steps": [], "last_error": entry["last_error"]})
    return {"address": address, "name": device.name, "paired": coordinator.is_device_paired(address),
            "confirmed": confirmed, "values": values, "has_draft": bool(draft),
            "draft_blocks": (["temperature"] if any(key in draft for key in CONFIG_KEYS) else [])
                            + (["week_profile"] if dirty_days else []),
            "locks": locks,
            "jobs": jobs}


class RoomConfigManager:
    """Serialize short admission transactions; never hold a lock during RF work."""

    def __init__(self, hass, controllers: dict, members=None):
        self.hass = hass
        self.controllers = controllers
        self.members = members or (lambda: registry_members(hass, controllers))
        self._save_lock = asyncio.Lock()

    def snapshot(self) -> dict:
        grouped = {}
        for member in self.members():
            coordinator = self.controllers.get(member["config_entry_id"])
            if coordinator is None or coordinator.get_device(member["address"]) is None:
                continue
            room = grouped.setdefault(member["area_id"], {"id": member["area_id"], "name": member["area_name"], "devices": []})
            item = device_snapshot(coordinator, member["address"])
            item["config_entry_id"] = member["config_entry_id"]
            if not any(d["address"] == item["address"] and d["config_entry_id"] == item["config_entry_id"] for d in room["devices"]):
                room["devices"].append(item)
        for room in grouped.values():
            room["devices"].sort(key=lambda d: (d["config_entry_id"], d["address"]))
            values = {}
            mixed = []
            def common(key, day=None):
                entries = [d["values"][key][day] if day else d["values"][key] for d in room["devices"]]
                if any(value != entries[0] for value in entries[1:]):
                    mixed.append(day or key)
                    return None
                return entries[0]
            for key in TEMPERATURE_KEYS:
                values[key] = common(key)
            values["week_profile"] = {key: common("week_profile", key) for key in DAY_LABELS}
            room.update(values=values, mixed=mixed, has_draft=any(d["has_draft"] for d in room["devices"]))
            room["locks"] = {block: any(d["locks"][block] for d in room["devices"]) for block in ("temperature", "week_profile")}
            room["revision"] = {}
            for block in room["locks"]:
                data = [{"owner": d["config_entry_id"], "address": d["address"], "paired": d["paired"],
                         "values": d["values"]["week_profile"] if block == "week_profile" else
                                   {k: d["values"][k] for k in TEMPERATURE_KEYS},
                         "locked": d["locks"][block], "draft": block in d["draft_blocks"],
                         "offset": self.controllers[d["config_entry_id"]].get_temperature_config_value(d["address"], "measurement_offset")
                                   if block == "temperature" else None}
                        for d in room["devices"]]
                room["revision"][block] = fingerprint(data)
        return {"rooms": sorted(grouped.values(), key=lambda r: r["name"].casefold())}

    async def save(self, area_id: str, changes: dict, expected_revision: dict, operation_id: str) -> dict:
        from .coordinator import PendingClimateCommand
        if not isinstance(changes, dict) or set(changes) - {*TEMPERATURE_KEYS, "week_profile"}:
            raise ValueError("Unbekannte Konfigurationswerte")
        if not operation_id or len(operation_id) > 80:
            raise ValueError("Ungültige Auftrags-ID")
        request_hash = fingerprint({"area_id": area_id, "changes": changes})
        async with self._save_lock:
            previous = [job for c in self.controllers.values() for job in c._config_jobs.values()
                        if job.get("operation_id") == operation_id]
            if previous:
                if any(job.get("request_hash") != request_hash for job in previous):
                    raise ValueError("Auftrags-ID gehört zu anderen Änderungen")
                return {"operation_id": operation_id, "job_ids": [job["id"] for job in previous], "status": "accepted"}
            room = next((r for r in self.snapshot()["rooms"] if r["id"] == area_id), None)
            if room is None:
                raise ValueError("Raum nicht mehr vorhanden oder ohne MAX!-Thermostate")
            cleaned = {}
            for key, value in changes.items():
                if key == "week_profile":
                    if not isinstance(value, dict) or set(value) - DAY_LABELS.keys():
                        raise ValueError("Ungültige Wochentage")
                    lines = "\n".join(f"{DAY_LABELS[k]} {v}" for k, v in value.items())
                    if value:
                        parse_week_profile_text(lines)
                    cleaned[key] = value
                elif key == "window_open_duration":
                    number = float(value)
                    if number != int(number) or not 0 <= number <= 60 or number % 5:
                        raise ValueError("Fenster-offen-Dauer: 0 bis 60 Minuten in 5-Minuten-Schritten")
                    cleaned[key] = int(number)
                else:
                    cleaned[key] = parse_max_temperature(str(value))
            blocks = ({"temperature"} if set(cleaned) & set(TEMPERATURE_KEYS) else set())
            if cleaned.get("week_profile"):
                blocks.add("week_profile")
            blocks.update(block for d in room["devices"] for block in d["draft_blocks"] if not room["locks"][block])
            for block in blocks:
                if room["locks"][block]:
                    raise ValueError("Dieser Konfigurationsblock ist bereits eingereiht")
                if expected_revision.get(block) != room["revision"][block]:
                    raise ValueError("Konfiguration wurde zwischenzeitlich geändert. Bitte neu laden.")
            plans = []
            for item in room["devices"]:
                c = self.controllers[item["config_entry_id"]]
                address = item["address"]
                c._require_paired_for_write(address)
                device = c.get_device(address)
                draft = c.get_config_draft(address)
                temp_changes = {k: draft[k] for k in CONFIG_KEYS if k in draft} if "temperature" in blocks else {}
                temp_changes.update({k: v for k, v in cleaned.items() if k in TEMPERATURE_KEYS})
                if temp_changes and any(v != getattr(device, k) for k, v in temp_changes.items()):
                    c.ensure_config_available(address, "temperature")
                    full = {k: temp_changes.get(k, getattr(device, k)) for k in TEMPERATURE_KEYS}
                    full["measurement_offset"] = temp_changes.get("measurement_offset", device.measurement_offset)
                    # Validate legacy drafts too, before admitting ANY device.
                    from .protocol import build_config_temperatures
                    build_config_temperatures(0, c.own_address, int(address, 16), **full,
                                              maximum_temperature=device.maximum_temperature,
                                              minimum_temperature=device.minimum_temperature)
                    job_id = str(uuid4())
                    commands = [PendingClimateCommand("config_temperatures", f"ConfigTemperatures {device.name}",
                                                       temperature_config=full, job_id=job_id, admitted=False)]
                    plans.append((c, address, "temperature", commands))
                days = ({k: draft["week_profile_by_day"][k] for k in draft.get("week_profile_dirty_days", [])}
                        if "week_profile" in blocks else {})
                days.update(cleaned.get("week_profile", {}))
                local = format_week_profile_by_day(c.get_local_week_profile(address)) if device.week_profile else {}
                days = {k: v for k, v in days.items() if v != local.get(k) or
                        device.week_profile_known_days is not None and DAY_INDEX[k] not in device.week_profile_known_days}
                if days:
                    c.ensure_config_available(address, "week_profile")
                    updates = parse_week_profile_text("\n".join(f"{DAY_LABELS[k]} {v}" for k, v in days.items()))
                    target = encode_week_profile(updates, c.get_local_week_profile(address))
                    job_id = str(uuid4())
                    commands = [PendingClimateCommand("config_week_profile", f"ConfigWeekProfile {device.name} {day} / {part}",
                                day=day, part=part, chunk_hex=chunk, profile_hex=target,
                                job_id=job_id, admitted=False)
                                for day in sorted(updates) for part, chunk in split_week_profile_for_send(target, day)]
                    plans.append((c, address, "week_profile", commands))
            # No await between reservations. Workers cannot consume uncommitted commands.
            for c, address, block, commands in plans:
                for command in commands:
                    command.queued_at = c._now_iso()
                c._pending_climate_config.setdefault(address, []).extend(commands)
                c._ensure_config_jobs()
                c._config_jobs[commands[0].job_id].update(operation_id=operation_id, request_hash=request_hash,
                                                        area_id=area_id, block=block, operation_size=len(plans))
            touched = {c for c, _, _, _ in plans}
            try:
                for c in touched:
                    await c._save_devices()
            except BaseException:
                ids = {commands[0].job_id for _, _, _, commands in plans}
                for c in touched:
                    for address in list(c._pending_climate_config):
                        remaining = [cmd for cmd in c._pending_climate_config[address] if cmd.job_id not in ids]
                        if remaining:
                            c._pending_climate_config[address] = remaining
                        else:
                            del c._pending_climate_config[address]
                    for job_id in ids:
                        c._config_jobs.pop(job_id, None)
                await asyncio.gather(*(c._save_devices() for c in touched), return_exceptions=True)
                raise
            for item in room["devices"]:
                c = self.controllers[item["config_entry_id"]]
                draft = c._config_drafts.get(item["address"], {})
                if "temperature" in blocks:
                    for key in CONFIG_KEYS:
                        draft.pop(key, None)
                if "week_profile" in blocks:
                    draft.pop("week_profile_by_day", None)
                    draft.pop("week_profile_dirty_days", None)
                if not draft:
                    c._config_drafts.pop(item["address"], None)
                c._notify_diagnostics_updated(item["address"])
                c._notify_week_profile_updated(item["address"])
            for c, address, _, commands in plans:
                for command in commands:
                    command.admitted = True
                await c._sync_pending_config_reading(address)
                c._notify_week_profile_updated(address)
                c._schedule_climate_config_processing(address, trigger="room_save")
            return {"operation_id": operation_id, "job_ids": [cmds[0].job_id for _, _, _, cmds in plans],
                    "status": "accepted" if plans else "unchanged"}

    async def discard(self, area_id: str, expected_revision: dict) -> dict:
        """Discard drafts only. Queued work and confirmed values are untouched."""
        async with self._save_lock:
            room = next((r for r in self.snapshot()["rooms"] if r["id"] == area_id), None)
            if room is None:
                raise ValueError("Raum nicht mehr vorhanden")
            blocks = {block for d in room["devices"] for block in d["draft_blocks"]}
            if any(expected_revision.get(block) != room["revision"][block] for block in blocks):
                raise ValueError("Entwurf wurde zwischenzeitlich geändert. Bitte neu laden.")
            for item in room["devices"]:
                await self.controllers[item["config_entry_id"]].async_discard_config_draft(item["address"])
            return {"status": "discarded"}
