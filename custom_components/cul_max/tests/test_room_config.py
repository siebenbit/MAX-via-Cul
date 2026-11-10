"""Room saves, partial ACKs and conflict protection, entirely without RF hardware."""
from __future__ import annotations

import asyncio
import importlib
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

import test_credit as transport

mod, protocol = transport.mod, transport.protocol
room_module = importlib.import_module("_cul_budget_tests.room_config")


class RoomConfigTests(unittest.IsolatedAsyncioTestCase):
    attach = transport.CreditTests.attach
    settle = transport.CreditTests.settle
    asyncTearDown = transport.CreditTests.asyncTearDown

    async def asyncSetUp(self):
        await transport.CreditTests.asyncSetUp(self)
        self.cul.credits = 900
        self.cul.frame_hook = lambda cul, cmd: cul.feed(transport.ack_line(cmd))
        self.c._command_worker_task = asyncio.create_task(self.c._command_worker())
        self.c._schedule_climate_config_processing = lambda *args, **kwargs: None
        self.c._maybe_sync_time_after_climate_config = AsyncMock()
        self.members = []
        for index, address in enumerate(("123456", "234567", "345678")):
            self.c._devices[address] = mod.KnownDevice(address, 1, f"Thermostat {index}", paired=True,
                                                       week_profile=mod.DEFAULT_WEEK_PROFILE)
            self.members.append({"area_id": "living" if index < 2 else "bed", "area_name": "Wohnzimmer" if index < 2 else "Schlafzimmer",
                                 "config_entry_id": "cul", "address": address})
        self.manager = room_module.RoomConfigManager(self.c.hass, {"cul": self.c}, lambda: self.members)

    def room(self, area="living"):
        return next(r for r in self.manager.snapshot()["rooms"] if r["id"] == area)

    async def save(self, changes, area="living", operation="operation-1", revision=None):
        return await self.manager.save(area, changes, revision or self.room(area)["revision"], operation)

    async def drain(self):
        tasks = [asyncio.create_task(self.c._process_climate_config_queue(address, trigger="test"))
                 for address in list(self.c._pending_climate_config)]
        self.tasks.extend(tasks)
        await asyncio.wait_for(asyncio.gather(*tasks), 3)

    async def test_admission_has_one_save_and_replay_wakes_existing_work(self):
        self.c._save_devices = AsyncMock(side_effect=[None, OSError("unexpected second save")])
        revision = self.room()["revision"]
        result = await self.save({"eco_temperature": 18}, revision=revision)
        self.assertEqual(self.c._save_devices.await_count, 1)
        self.assertTrue(all(cmd.admitted for q in self.c._pending_climate_config.values() for cmd in q))
        self.c._schedule_climate_config_processing = lambda *args, **kwargs: calls.append(args[0])
        calls = []
        # Also recover an operation left blocked by an earlier software version.
        self.c._pending_climate_config["234567"][0].admitted = False
        replay = await self.save({"eco_temperature": 18}, revision=revision)
        self.assertEqual(result["job_ids"], replay["job_ids"])
        self.assertEqual(set(calls), {"123456", "234567"})
        self.assertTrue(self.c._pending_climate_config["234567"][0].admitted)
        self.assertEqual(sum(map(len, self.c._pending_climate_config.values())), 2)

    async def test_room_snapshot_aggregates_mixed_values_without_selecting_a_device(self):
        self.c.get_device("234567").eco_temperature = 18
        result = self.room()
        self.assertIsNone(result["values"]["eco_temperature"])
        self.assertIn("eco_temperature", result["mixed"])
        self.assertEqual(result["values"]["comfort_temperature"], 21)
        self.assertEqual(len(result["devices"]), 2)
        self.assertFalse(self.cul.commands)

    async def test_one_save_admits_both_blocks_for_all_room_devices_and_only_ack_updates_values(self):
        result = await self.save({"comfort_temperature": 22, "week_profile": {"monday": "17,06:00,21,22:00,17"}})
        self.assertEqual(len(result["job_ids"]), 4)
        self.assertTrue(self.room()["locks"]["temperature"])
        self.assertTrue(self.room()["locks"]["week_profile"])
        self.assertEqual(self.room()["values"]["comfort_temperature"], 22)
        self.assertEqual(self.room()["devices"][0]["confirmed"]["comfort_temperature"], 21)
        self.assertFalse(self.cul.commands)
        await self.drain()
        self.assertFalse(any(self.room()["locks"].values()))
        self.assertEqual(self.c.get_device("123456").comfort_temperature, 22)
        self.assertEqual(self.c.get_device("234567").comfort_temperature, 22)
        self.assertEqual(self.c.get_device("345678").comfort_temperature, 21)
        self.assertEqual(protocol.format_week_profile_by_day(self.c.get_device("123456").week_profile)["monday"], "17,06:00,21,22:00,17")
        self.assertTrue(all(job["status"] == "completed" for job in self.c._config_jobs.values()))

    async def test_duplicate_request_returns_same_jobs_even_while_locked(self):
        revision = self.room()["revision"]
        changes = {"eco_temperature": 18}
        first = await self.save(changes, revision=revision)
        second = await self.save(changes, revision=revision)
        self.assertEqual(first, second)
        self.assertEqual(sum(len(q) for q in self.c._pending_climate_config.values()), 2)
        with self.assertRaisesRegex(ValueError, "anderen"):
            await self.save({"eco_temperature": 19}, revision=revision)

    async def test_invalid_inputs_or_one_unpaired_device_cannot_partially_enqueue(self):
        for changes in ({"eco_temperature": 18.2}, {"window_open_duration": 2},
                        {"week_profile": {"monday": "17,06:01,21"}}, {"other": 1}):
            with self.assertRaises(ValueError):
                await self.save(changes)
            self.assertFalse(self.c._pending_climate_config)
        self.c.get_device("234567").paired = False
        with self.assertRaises(ValueError):
            await self.save({"eco_temperature": 18})
        self.assertFalse(self.c._pending_climate_config)
        self.assertFalse(self.cul.commands)

    async def test_stale_value_or_membership_revision_rejects_all_devices(self):
        revision = self.room()["revision"]
        self.c.get_device("123456").eco_temperature = 18
        with self.assertRaisesRegex(ValueError, "zwischenzeitlich"):
            await self.save({"eco_temperature": 19}, revision=revision)
        revision = self.room()["revision"]
        self.members[1]["area_id"] = "bed"
        with self.assertRaisesRegex(ValueError, "zwischenzeitlich"):
            await self.save({"eco_temperature": 19}, revision=revision)
        self.assertFalse(self.c._pending_climate_config)

    async def test_busy_temperature_blocks_legacy_edits_but_week_profile_remains_writable(self):
        revision = self.room()["revision"]
        await self.save({"comfort_temperature": 22})
        with self.assertRaises(ValueError):
            await self.c.async_set_temperature_config_draft("123456", "eco_temperature", 18)
        with self.assertRaises(ValueError):
            await self.c.async_set_eco_temperature("123456", 18)
        second = await self.save({"week_profile": {"monday": "19"}}, operation="operation-2", revision=revision)
        self.assertEqual(len(second["job_ids"]), 2)
        with self.assertRaises(ValueError):
            await self.c.async_set_week_profile("123456", "Mon 20")

    async def test_legacy_drafts_are_snapshot_consumed_including_offset(self):
        await self.c.async_set_temperature_config_draft("123456", "comfort_temperature", 22)
        await self.c.async_set_temperature_config_draft("123456", "measurement_offset", 1)
        await self.c.async_set_week_profile_day_draft("123456", "monday", "19")
        await self.save({})
        self.assertFalse(self.c.has_config_draft("123456"))
        await self.drain()
        self.assertEqual(self.c.get_device("123456").comfort_temperature, 22)
        self.assertEqual(self.c.get_device("123456").measurement_offset, 1)

    async def test_persistence_failure_rolls_back_reservations_and_keeps_drafts(self):
        await self.c.async_set_temperature_config_draft("123456", "comfort_temperature", 22)
        self.c._save_devices = AsyncMock(side_effect=OSError("disk full"))
        with self.assertRaises(OSError):
            await self.save({"eco_temperature": 18})
        self.assertFalse(self.c._pending_climate_config)
        self.assertFalse(self.c._config_jobs)
        self.assertTrue(self.c.has_config_draft("123456"))
        self.assertFalse(self.cul.commands)

    async def test_admission_cannot_send_before_persistence_completes(self):
        gate = asyncio.Event()
        async def save_wait():
            await gate.wait()
        self.c._save_devices = save_wait
        request = asyncio.create_task(self.save({"eco_temperature": 18}))
        self.tasks.append(request)
        await self.settle()
        await self.c._process_climate_config_queue("123456", trigger="test")
        self.assertFalse(self.cul.commands)
        self.assertTrue(self.c.config_busy("123456", "temperature"))
        gate.set()
        await asyncio.wait_for(request, 1)

    async def test_partial_profile_is_not_marked_confirmed_and_cancel_is_persistent(self):
        long_day = "17,01:00,18,02:00,19,03:00,20,04:00,21,05:00,22,06:00,23,07:00,24"
        await self.save({"week_profile": {"monday": long_day}})
        previous = self.c.get_device("123456").week_profile
        calls = 0
        def ack_first(cul, cmd):
            nonlocal calls
            calls += 1
            cul.feed(transport.ack_line(cmd)[:-2] + ("00" if calls == 1 else "81"))
        self.cul.frame_hook = ack_first
        await self.c._process_climate_config_queue("123456", trigger="test")
        self.assertEqual(self.c.get_device("123456").week_profile, previous)
        self.assertIsNone(self.room()["devices"][0]["confirmed"]["week_profile"]["monday"])
        job_id = self.c._pending_climate_config["123456"][0].job_id
        self.assertEqual(len(self.c._config_jobs[job_id]["confirmed_steps"]), 1)
        await self.c.async_cancel_config_job(job_id, confirm=True)
        self.assertNotIn("123456", self.c._pending_climate_config)
        self.assertTrue(self.c._config_jobs[job_id]["cancel_requested"])

    async def test_discard_removes_only_unsaved_drafts_not_queued_jobs(self):
        await self.save({"eco_temperature": 18})
        await self.c.async_set_week_profile_day_draft("123456", "monday", "19")
        await self.manager.discard("living", self.room()["revision"])
        self.assertFalse(self.c.has_config_draft("123456"))
        self.assertTrue(self.c.config_busy("123456", "temperature"))
        self.assertFalse(self.cul.commands)

    async def test_unchanged_values_generate_no_rf_job(self):
        result = await self.save({"comfort_temperature": 21})
        self.assertEqual(result["status"], "unchanged")
        self.assertFalse(self.c._pending_climate_config)

    async def test_budget_wait_retains_pending_values_and_locks(self):
        self.cul.credits = 0
        await self.save({"comfort_temperature": 22})
        process = asyncio.create_task(self.c._process_climate_config_queue("123456", trigger="test"))
        self.tasks.append(process)
        await asyncio.sleep(.12)
        await self.settle()
        self.assertFalse(self.cul.frames)
        self.assertEqual(self.room()["values"]["comfort_temperature"], 22)
        self.assertTrue(self.room()["locks"]["temperature"])
        self.assertEqual(self.room()["devices"][0]["jobs"][0]["status"], "waiting_for_credits")
        self.cul.credits = 900
        self.c._radio_changed.set()
        await asyncio.wait_for(process, 2)

    async def test_pending_temperature_configuration_restores_and_completes(self):
        await self.save({"eco_temperature": 18})
        self.c._store = types.SimpleNamespace(async_save=AsyncMock())
        await mod.CulMaxCoordinator._save_devices(self.c)
        saved = self.c._store.async_save.call_args.args[0]
        await self.c.async_shutdown()
        self.c = mod.CulMaxCoordinator(types.SimpleNamespace(loop=self.clock), "simulated")
        self.c._schedule_reconnect = lambda: None
        self.c._store = types.SimpleNamespace(async_load=AsyncMock(return_value=saved))
        self.c._save_devices = AsyncMock()
        self.c._sync_device_registry_entry = AsyncMock()
        self.c._maybe_sync_time_after_climate_config = AsyncMock()
        self.c._touch_device = AsyncMock()
        await self.c._load_devices()
        self.attach(credits=900)
        self.cul.frame_hook = lambda cul, cmd: cul.feed(transport.ack_line(cmd))
        self.c._command_worker_task = asyncio.create_task(self.c._command_worker())
        await self.drain()
        self.assertEqual(self.c.get_device("123456").eco_temperature, 18)
        self.assertFalse(self.c._pending_climate_config)

    async def test_registry_uses_entity_area_override_and_never_rf_group_names(self):
        entities = types.SimpleNamespace(entities={"x": types.SimpleNamespace(
            platform="cul_max", domain="climate", config_entry_id="cul", device_id="device", area_id="override", unique_id="cul_max_123456")})
        devices = types.SimpleNamespace(async_get=lambda _: types.SimpleNamespace(area_id="default"))
        areas = types.SimpleNamespace(async_get_area=lambda area_id: types.SimpleNamespace(id=area_id, name=area_id))
        names = {name: types.ModuleType(name) for name in ("homeassistant", "homeassistant.helpers", "homeassistant.helpers.area_registry",
                 "homeassistant.helpers.device_registry", "homeassistant.helpers.entity_registry")}
        for name, registry in (("area", areas), ("device", devices), ("entity", entities)):
            names[f"homeassistant.helpers.{name}_registry"].async_get = lambda _, registry=registry: registry
        with patch.dict(sys.modules, names):
            members = room_module.registry_members(self.c.hass, {"cul": self.c})
        self.assertEqual(members[0]["area_id"], "override")
        self.assertEqual(len(members), 1)

    async def test_two_simultaneous_saves_cannot_claim_the_same_block(self):
        revision = self.room()["revision"]
        result = await asyncio.gather(self.save({"eco_temperature": 18}, operation="a", revision=revision),
                                      self.save({"eco_temperature": 19}, operation="b", revision=revision), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, ValueError) for r in result), 1)
        self.assertEqual(len(self.c._config_jobs), 2)

    async def test_seven_day_profile_confirms_only_its_uploaded_days(self):
        self.cul.frame_hook = lambda cul, cmd: (cul.feed(transport.ack_line(cmd)), setattr(cul, "credits", 900))
        await self.save({"week_profile": {day: "20" for day in room_module.DAY_LABELS}})
        with patch.object(mod, "WEEK_PROFILE_PART_DELAY", 0):
            await self.drain()
        device = self.c.get_device("123456")
        self.assertEqual(set(device.week_profile_known_days), set(range(7)))
        self.assertTrue(all(value == "20" for value in protocol.format_week_profile_by_day(device.week_profile).values()))

    async def test_legacy_apply_uses_the_same_persistent_admission(self):
        await self.c.async_set_temperature_config_draft("123456", "comfort_temperature", 22)
        await self.c.async_apply_config_draft("123456")
        self.assertTrue(self.c.config_busy("123456", "temperature"))
        self.assertFalse(self.c.has_config_draft("123456"))
        self.assertFalse(self.cul.frames)

    async def test_live_hub_coalesces_notifications_and_rebinds_new_devices(self):
        class Bus:
            def __init__(self):
                self.callbacks = []
            def async_listen(self, name, callback):
                self.callbacks.append(callback)
                return lambda: self.callbacks.remove(callback)
            async_listen_once = async_listen
        self.c.hass.data = {"cul_max_queue_controllers": {"cul": self.c}}
        self.c.hass.bus = Bus()
        core = types.ModuleType("homeassistant.core")
        core.callback = lambda func: func
        with patch.dict(sys.modules, {"homeassistant.core": core}):
            api = importlib.import_module("_cul_budget_tests.room_config_api")
        hub = api.RoomConfigHub(self.c.hass)
        hub.manager.members = lambda: self.members
        received = []
        unsubscribe = hub.subscribe(received.append)
        for _ in range(50):
            hub.changed()
        await asyncio.sleep(.12)
        before = len(received)
        for _ in range(50):
            hub.changed()
        await asyncio.sleep(.12)
        self.assertEqual(len(received), before)
        self.c._devices["456789"] = mod.KnownDevice("456789", 1, "new", paired=True)
        hub.changed()
        await asyncio.sleep(.12)
        self.assertIn((id(self.c), "456789"), hub.bound_devices)
        unsubscribe()
        self.assertIsNone(hub.timer)
        hub.close()
        self.assertFalse(self.c.hass.bus.callbacks)

    async def test_room_actions_and_subscription_are_registered_as_admin_only(self):
        registrations, commands = [], []
        fake = {name: types.ModuleType(name) for name in (
            "voluptuous", "homeassistant", "homeassistant.components", "homeassistant.components.websocket_api",
            "homeassistant.core", "homeassistant.exceptions", "homeassistant.helpers",
            "homeassistant.helpers.config_validation", "homeassistant.helpers.service")}
        fake["voluptuous"].Required = lambda name: name
        fake["voluptuous"].Schema = lambda schema: schema
        fake["homeassistant.core"].callback = lambda func: func
        fake["homeassistant.core"].SupportsResponse = types.SimpleNamespace(ONLY="only")
        fake["homeassistant.exceptions"].ServiceValidationError = ValueError
        fake["homeassistant.helpers.config_validation"].string = str
        fake["homeassistant.helpers.service"].async_register_admin_service = lambda *args: registrations.append(args)
        ws = fake["homeassistant.components.websocket_api"]
        ws.websocket_command = lambda schema: lambda func: func
        ws.async_response = lambda func: func
        def admin(func):
            func.requires_admin = True
            return func
        ws.require_admin = admin
        ws.async_register_command = lambda hass, func: commands.append(func)
        self.c.hass.data = {"cul_max_queue_controllers": {"cul": self.c}}
        self.c.hass.bus = types.SimpleNamespace(async_listen=lambda *args: lambda: None,
                                               async_listen_once=lambda *args: lambda: None)
        self.c.hass.services = types.SimpleNamespace(has_service=lambda *args: False)
        with patch.dict(sys.modules, fake):
            api = importlib.import_module("_cul_budget_tests.room_config_api")
            api.register_room_config_api(self.c.hass)
        self.assertEqual({item[2] for item in registrations}, set(api.SERVICES))
        self.assertTrue(all(item[-1] == "only" for item in registrations))
        self.assertTrue(commands[0].requires_admin)
        self.c.hass.data[api.DATA_KEY].close()

    async def test_reverting_legacy_drafts_leaves_no_stale_dirty_state(self):
        await self.c.async_set_temperature_config_draft("123456", "eco_temperature", 18)
        await self.c.async_set_temperature_config_draft("123456", "eco_temperature", 17)
        self.assertFalse(self.c.has_config_draft("123456"))
        baseline = self.c.get_week_profile_day_value("123456", "monday")
        await self.c.async_set_week_profile_day_draft("123456", "monday", "19")
        await self.c.async_set_week_profile_day_draft("123456", "monday", baseline)
        self.assertFalse(self.c.has_config_draft("123456"))
        with self.assertRaises(ValueError):
            await self.c.async_set_temperature_config_draft("123456", "window_open_duration", 5.5)
        self.assertFalse(self.cul.commands)

    async def test_pending_target_wins_over_an_older_legacy_draft(self):
        await self.c.async_set_temperature_config_draft("123456", "eco_temperature", 18)
        # A legacy direct action may already own an older unsaved draft.
        self.c._pending_climate_config["123456"] = [mod.PendingClimateCommand(
            "config_temperatures", "ConfigTemperatures", temperature_config={"eco_temperature": 19})]
        snapshot = room_module.device_snapshot(self.c, "123456")
        self.assertEqual(snapshot["values"]["eco_temperature"], 19)
        self.assertTrue(snapshot["has_draft"])

    async def test_older_draft_in_busy_block_does_not_block_saving_free_block(self):
        await self.c.async_set_temperature_config_draft("123456", "eco_temperature", 18)
        self.c._pending_climate_config["123456"] = [mod.PendingClimateCommand(
            "config_temperatures", "ConfigTemperatures", temperature_config={"eco_temperature": 19})]
        result = await self.save({"week_profile": {"monday": "20"}})
        self.assertEqual(len(result["job_ids"]), 2)
        self.assertTrue(self.c.has_config_draft("123456"))
        self.assertEqual(self.c.get_config_draft("123456")["eco_temperature"], 18)

    async def test_upgrade_does_not_treat_old_pending_target_as_confirmed_profile(self):
        command = mod.PendingClimateCommand("config_week_profile", "ConfigWeekProfile", day=2, part=0,
                                            chunk_hex="28" * 14, profile_hex=mod.DEFAULT_WEEK_PROFILE)
        saved = {"schema_version": mod.STORAGE_SCHEMA_VERSION,
                 "devices": {"123456": {"address": "123456", "device_type": 1, "name": "old",
                                         "week_profile": mod.DEFAULT_WEEK_PROFILE}},
                 "pending_climate_config": {"123456": [mod._serialize_pending_climate_command(command)]}}
        self.c._store = types.SimpleNamespace(async_load=AsyncMock(return_value=saved))
        self.c._sync_device_registry_entry = AsyncMock()
        await self.c._load_devices()
        self.assertNotIn(2, self.c.get_device("123456").week_profile_known_days)
        self.assertEqual(len(self.c.get_device("123456").week_profile_known_days), 6)
