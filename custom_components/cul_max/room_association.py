"""Small area-to-group mapping; reuse coordinator association and deferred work."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from copy import deepcopy

from homeassistant.helpers.storage import Store

from .const import DOMAIN, CLIMATE_DEVICE_TYPES, DEVICE_SHUTTER_CONTACT, DEVICE_TYPE_NAMES_DE, DEFAULT_DEVICE_TYPE_NAME_DE
from .queue_api import select_controller
from .protocol import parse_message
from .room_config import registry_members

DATA_KEY = f"{DOMAIN}_room_associations"
_OWNER = ContextVar("cul_max_association_owner", default=None)


class RoomAssociationManager:
    def __init__(self, hass, controllers, members=None):
        self.hass = hass
        self.controllers = controllers
        self.members = members or (lambda: registry_members(hass, controllers, include_windows=True))
        self.store = Store(hass, 1, f"{DOMAIN}_room_associations")
        self.records = {}
        self.tasks = {}
        self.admitting = set()
        self.unloading = set()
        self.errors = {}
        self.lock = asyncio.Lock()
        self.changed = lambda: None

    async def load(self):
        data = await self.store.async_load() or {}
        self.records = data.get("controllers", {})
        for records in self.records.values():
            for record in records.values():
                if (not isinstance(record.get("group_id"), int) or not 1 <= record["group_id"] <= 255
                        or not isinstance(record.get("members"), list)
                        or not all(isinstance(a, str) for a in record["members"])):
                    raise ValueError("Ungültige gespeicherte Raumzuordnung")

    def record(self, owner, area):
        return self.records.get(owner, {}).get(area)

    def pending(self, c, record):
        addresses = record.get("members", [])
        pairs = set(c._iter_room_association_pairs(
            [a for a in addresses if c.get_device(a) and c.get_device(a).device_type in CLIMATE_DEVICE_TYPES],
            [a for a in addresses if c.get_device(a) and c.get_device(a).device_type == DEVICE_SHUTTER_CONTACT], bidirectional=True))
        return any((cmd.op == "set_group_id" and cmd.group_id == record["group_id"]
                    or cmd.op == "add_link_partner" and (address, cmd.partner_address) in pairs)
                   for address in addresses for cmd in c._pending_shutter_config.get(address, []))

    def busy(self, owner, area):
        record = self.record(owner, area)
        c = self.controllers.get(owner)
        return (owner, area) in self.admitting or (owner, area) in self.tasks or bool(record and c and self.pending(c, record))

    def queued_groups(self, c):
        groups = set()
        for entry in c._command_queue.entries.values():
            if entry.command_type != "SetGroupId":
                continue
            cmd = getattr(entry.payload, "cmd", "")
            msg = parse_message("Z" + cmd.strip()[2:]) if cmd.startswith("Zs") else None
            if msg and msg.payload:
                groups.add(msg.payload[0])
        return groups

    def groups_used(self, owner, c):
        return (c.get_used_group_ids() | self.queued_groups(c)
                | {r["group_id"] for r in self.records.get(owner, {}).values()}
                | {cmd.group_id for commands in c._pending_shutter_config.values() for cmd in commands
                   if cmd.op == "set_group_id" and cmd.group_id})

    def pending_external_links(self, c, addresses):
        """Include deferred and in-flight changes on either side of the room."""
        selected = set(addresses)
        for address, commands in c._pending_shutter_config.items():
            for command in commands:
                if command.op in {"add_link_partner", "remove_link_partner"} and command.partner_address:
                    if (address in selected) != (command.partner_address in selected):
                        return True
        for entry in c._command_queue.entries.values():
            if entry.command_type not in {"AddLinkPartner", "RemoveLinkPartner"}:
                continue
            cmd = getattr(entry.payload, "cmd", "")
            msg = parse_message("Z" + cmd.strip()[2:]) if cmd.startswith("Zs") else None
            if msg and len(msg.payload) >= 3:
                partner = msg.payload[:3].hex().upper()
                if (msg.dst_hex in selected) != (partner in selected):
                    return True
        return False

    def room(self, owner, area, members, name=None):
        c = self.controllers[owner]
        record = self.record(owner, area)
        selected = {m["address"] for m in members}
        busy = self.busy(owner, area)
        addresses = record["members"] if busy and record else sorted(selected)
        devices = []
        problems = []
        from homeassistant.helpers import device_registry as dr
        registry = dr.async_get(self.hass)
        for address in addresses:
            device = c.get_device(address)
            if not device:
                problems.append(f"Gerät {address} nicht mehr vorhanden")
                continue
            entry = registry.async_get_device(identifiers={(DOMAIN, address)})
            devices.append({"address": address, "name": (entry.name_by_user or entry.name or device.name) if entry else device.name,
                            "type": DEVICE_TYPE_NAMES_DE.get(device.device_type, DEFAULT_DEVICE_TYPE_NAME_DE),
                            "group_id": device.group_id, "pending": bool(c._pending_shutter_config.get(address))})
            if not c.is_device_paired(address):
                problems.append(f"{device.name}: noch nicht angelernt")
            if set(device.linked_partners) - set(addresses):
                problems.append(f"{device.name}: Verknüpfungen außerhalb dieses Raums")
        if any(d.linked_partners and set(d.linked_partners) & set(addresses)
               for d in c.get_all_devices() if d.address not in addresses):
            problems.append("Andere Geräte haben Verknüpfungen in diesen Raum")
        if self.pending_external_links(c, addresses):
            problems.append("Verknüpfungsbefehle über Raumgrenzen stehen noch aus")
        climates = [a for a in addresses if c.get_device(a) and c.get_device(a).device_type in CLIMATE_DEVICE_TYPES]
        windows = [a for a in addresses if c.get_device(a) and c.get_device(a).device_type == DEVICE_SHUTTER_CONTACT]
        if not climates or len(addresses) < 2:
            problems.append("Mindestens ein Thermostat und insgesamt zwei Geräte erforderlich")
        group = record["group_id"] if record else None
        if group and any(d.group_id == group for d in c.get_all_devices() if d.address not in addresses):
            problems.append(f"Gruppe {group} wird auch außerhalb dieses Raums verwendet")
        status = "running" if (owner, area) in self.tasks or (owner, area) in self.admitting else "pending_activity" if busy else "new"
        details = None
        if group:
            details = c._build_room_association_status(room_name=members[0]["area_name"] if members else area,
                climates=climates, windows=windows, group_id=group, bidirectional=True,
                created_virtual_address=None, errors=[])
            if not busy:
                status = details["status"]
        return {"id": area, "name": name or (members[0]["area_name"] if members else f"Entfernter Raum ({area})"),
                "devices": devices, "group_id": group, "status": status, "busy": busy,
                "problems": problems, "error": self.errors.get((owner, area)) if status != "complete" else None,
                "can_start": bool(owner not in self.unloading and not busy and not problems and c._writer is not None and status != "complete"),
                "details": details}

    def snapshot(self):
        members = self.members()
        from homeassistant.helpers import area_registry as ar
        names = {a.id: a.name for a in ar.async_get(self.hass).areas.values()}
        controllers = []
        for owner, c in self.controllers.items():
            areas = set(names) | set(self.records.get(owner, {}))
            rooms = [self.room(owner, area, [m for m in members if m["config_entry_id"] == owner and m["area_id"] == area], names.get(area))
                     for area in sorted(areas)]
            for room in rooms:
                room["other_devices"] = [self.controllers[m["config_entry_id"]].get_device(m["address"]).name
                    for m in members if m["area_id"] == room["id"] and m["config_entry_id"] != owner]
            controllers.append({"config_entry_id": owner, "name": f"MAX! CUL ({c.host}:{c.port})",
                                "rooms": sorted(rooms, key=lambda r: r["name"].casefold())})
        return {"controllers": controllers}

    async def start(self, owner, area):
        async with self.lock:
            c = select_controller(self.controllers, owner)
            members = [m for m in self.members() if m["config_entry_id"] == owner and m["area_id"] == area]
            if not members:
                raise ValueError("Raum enthält keine passenden MAX!-Geräte")
            room = self.room(owner, area, members)
            if not room["can_start"]:
                raise ValueError("; ".join(room["problems"]) or "Raum ist beschäftigt oder bereits verknüpft")
            addresses = sorted({m["address"] for m in members})
            for other, records in self.records.items():
                for other_area, record in records.items():
                    if other == owner and self.busy(other, other_area) and set(record["members"]) & set(addresses):
                        raise ValueError("Ein beteiligtes Gerät wird bereits verknüpft")
            if any(cmd.op in {"set_group_id", "remove_group_id", "add_link_partner", "remove_link_partner"}
                   for a in addresses for cmd in c._pending_shutter_config.get(a, [])):
                raise ValueError("Gruppen-/Verknüpfungsbefehle stehen noch aus")
            if any(entry.device_address in addresses and entry.command_type in {
                    "SetGroupId", "RemoveGroupId", "AddLinkPartner", "RemoveLinkPartner"}
                   for entry in c._command_queue.entries.values()):
                raise ValueError("Gruppen-/Verknüpfungsbefehle werden bereits übertragen")
            before = deepcopy(self.records)
            group = room["group_id"]
            if not group:
                existing = {c.get_device(a).group_id for a in addresses} - {0}
                candidate = next(iter(existing)) if len(existing) == 1 else None
                used = self.groups_used(owner, c)
                reserved = {r["group_id"] for r in self.records.get(owner, {}).values()}
                external = (any(d.group_id == candidate for d in c.get_all_devices() if d.address not in addresses)
                            or any(cmd.op == "set_group_id" and cmd.group_id == candidate
                                   for a, commands in c._pending_shutter_config.items() if a not in addresses
                                   for cmd in commands))
                group = candidate if candidate and not external and candidate not in reserved and candidate not in self.queued_groups(c) else next((g for g in range(1, 256) if g not in used), None)
                if group is None:
                    raise ValueError("Keine freie MAX!-Gruppen-ID verfügbar")
            self.records.setdefault(owner, {})[area] = {"group_id": group, "members": addresses}
            key = (owner, area)
            self.admitting.add(key)
            try:
                await self.store.async_save({"controllers": self.records})
            except BaseException:
                self.records = before
                raise
            finally:
                self.admitting.discard(key)
            self.errors.pop(key, None)
            self.tasks[key] = self.hass.loop.create_task(self.run(c, key, room["name"], addresses, group))
            self.changed()
        return {"status": "accepted", "group_id": group}

    async def run(self, c, key, name, addresses, group):
        token = _OWNER.set(key)
        try:
            result = await c.async_create_room_association(room_name=name, group_id=group,
                climate_addresses=[a for a in addresses if c.get_device(a).device_type in CLIMATE_DEVICE_TYPES],
                window_addresses=[a for a in addresses if c.get_device(a).device_type == DEVICE_SHUTTER_CONTACT])
            if result["errors"]:
                self.errors[key] = result["summary"]
        except asyncio.CancelledError:
            raise
        except Exception as err:
            self.errors[key] = str(err)
        finally:
            _OWNER.reset(token)
            self.tasks.pop(key, None)
            self.changed()

    def ensure_available(self, coordinator, address):
        owner = getattr(coordinator, "config_entry_id", None)
        for area, record in self.records.get(owner, {}).items():
            if address.upper() in record["members"] and self.busy(owner, area) and _OWNER.get() != (owner, area):
                raise ValueError("Raumverknüpfung läuft bereits")

    async def unload(self, owner):
        self.unloading.add(owner)
        async with self.lock:
            owned = {key: task for key, task in self.tasks.items() if key[0] == owner}
            tasks = list(owned.values())
            for task in tasks:
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for key, task in owned.items():
            if self.tasks.get(key) is task:
                self.tasks.pop(key, None)
        self.changed()
