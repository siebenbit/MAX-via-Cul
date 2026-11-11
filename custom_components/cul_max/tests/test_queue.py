"""Queue behavior through the production workers and simulated CUL streams."""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta, UTC
import importlib
import types
import unittest
from unittest.mock import AsyncMock

import test_credit as transport

mod = transport.mod
protocol = transport.protocol
api = importlib.import_module("_cul_budget_tests.queue_api")


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await transport.CreditTests.asyncSetUp(self)
        self.c._temperature_debounce_seconds = 0.0
    asyncTearDown = transport.CreditTests.asyncTearDown
    attach = transport.CreditTests.attach
    send = transport.CreditTests.send
    settle = transport.CreditTests.settle
    advance = transport.CreditTests.advance

    def worker(self):
        self.c._command_worker_task = asyncio.create_task(self.c._command_worker())

    def temperature(self, value, address="123456", mode=1, until=None):
        if not self.c.get_device(address):
            self.c._devices[address] = mod.KnownDevice(address, 1, f"Room {address}", paired=True)
        task = asyncio.create_task(self.c.async_set_temperature(address, value, mode=mode, until=until))
        self.tasks.append(task)
        return task

    def ack(self):
        self.cul.frame_hook = lambda cul, cmd: cul.feed(transport.ack_line(cmd))

    async def test_next_dispatch_is_read_only_and_maps_configuration_job(self):
        future = self.clock.create_future()
        entry = mod.QueueEntry("123456", "Room", "ConfigWeekProfile", "Profile", future,
                               job_id="job", scope="configuration")
        self.c._command_queue.add(entry)
        before = self.c._command_queue.qsize()
        for _ in range(2):
            self.assertEqual(self.c.get_queue()["next_dispatch"],
                             {"entry_id": entry.id, "job_id": "job"})
        self.assertEqual(self.c._command_queue.qsize(), before)
        self.c._command_queue.finish(entry, "cancelled")
        self.assertIsNone(self.c.get_queue()["next_dispatch"])

    async def test_next_dispatch_skips_blocked_entries_and_honors_radio_priority(self):
        blocked = mod.QueueEntry("123456", "Room", "Test", "Blocked", self.clock.create_future(),
                                 ready_task=self.clock.create_future(), ready_deadline=self.clock.time() + 60)
        ready = mod.QueueEntry("123456", "Room", "Test", "Ready", self.clock.create_future())
        self.c._command_queue.add(blocked)
        self.c._command_queue.add(ready)
        self.assertEqual(self.c.get_queue()["next_dispatch"]["entry_id"], ready.id)
        cmd = protocol.build_time_information(1, self.c.own_address, 0x123456)
        priority = mod.QueueEntry("123456", "Room", "Test", "Priority", self.clock.create_future())
        self.c._radio_requests = [
            types.SimpleNamespace(entry=ready, cmd=cmd, priority=False, sequence=1,
                                  future=self.clock.create_future(), written=False),
            types.SimpleNamespace(entry=priority, cmd=cmd, priority=True, sequence=2,
                                  future=self.clock.create_future(), written=False)]
        self.assertEqual(self.c.get_queue()["next_dispatch"]["entry_id"], priority.id)
        self.c._radio_requests[1].written = True
        self.assertIsNone(self.c.get_queue()["next_dispatch"])
        for request in self.c._radio_requests:
            request.future.cancel()
        self.c._radio_requests.clear()
        self.c._command_queue.finish(blocked, "cancelled")
        self.c._command_queue.finish(ready, "cancelled")

    async def test_only_latest_temperature_is_transmitted(self):
        self.cul.credits = 0
        self.worker()
        first = self.temperature(20)
        await self.settle()
        second = self.temperature(21)
        await self.settle()
        third = self.temperature(23)
        await self.settle()
        self.assertEqual((await first).status, "superseded")
        self.assertEqual((await second).status, "superseded")
        self.assertEqual(self.c._command_queue.superseded_count, 2)
        self.assertEqual(len(self.c._command_queue.entries), 1)
        self.assertEqual(self.cul.frames, [])
        self.ack()
        await self.advance(300, credits=450)
        self.assertEqual((await asyncio.wait_for(third, .5)).status, "completed")
        packet = bytes.fromhex(self.cul.frames[0][2:])
        self.assertEqual(packet[11] & 63, 46)
        self.assertEqual(len(self.cul.frames), 1)
        self.assertEqual(packet[1], 1)

    async def test_devices_and_other_command_types_are_independent(self):
        a = self.temperature(20)
        b = self.temperature(19, "234567")
        await self.settle()
        time_cmd = protocol.build_time_information(4, self.c.own_address, 0x123456)
        time_task = asyncio.create_task(self.c._send_command(time_cmd, expected_src=None,
            device_address="123456", counter=None, description="TimeInformation"))
        self.tasks.append(time_task)
        await self.settle()
        newest = self.temperature(23)
        await self.settle()
        self.assertEqual((await a).status, "superseded")
        self.assertFalse(b.done())
        self.assertFalse(time_task.done())
        self.assertEqual([e.command_type for e in self.c._command_queue.entries.values()],
                         ["SetTemperature", "TimeInformation", "SetTemperature"])
        self.ack()
        self.worker()
        await asyncio.wait_for(asyncio.gather(b, time_task, newest), .5)
        self.assertEqual(len(self.cul.frames), 3)

    async def test_modes_are_complete_replacement_intents(self):
        self.cul.credits = 0
        self.worker()
        tasks = [self.temperature(20, mode=1), self.temperature(0, mode=0),
                 self.temperature(0, mode=3), self.temperature(18, mode=2, until=(datetime.now(UTC) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0))]
        await self.settle()
        for task in tasks[:-1]:
            self.assertEqual((await asyncio.wait_for(task, .5)).status, "superseded")
        self.ack()
        await self.advance(300, credits=450)
        await asyncio.wait_for(tasks[-1], .5)
        packet = bytes.fromhex(self.cul.frames[0][2:])
        self.assertEqual(packet[11] >> 6, 2)
        self.assertEqual(len(packet), 15)
        self.assertEqual(len(self.cul.frames), 1)

    async def test_delete_active_credit_waiter_resolves_future(self):
        self.cul.credits = 0
        self.worker()
        task = self.temperature(20)
        await self.settle()
        entry = next(iter(self.c._command_queue.entries.values()))
        self.assertEqual(entry.status, "waiting_for_credits")
        self.c._command_queue.delete(entry.id)
        self.assertEqual((await asyncio.wait_for(task, .5)).status, "cancelled")
        await self.advance(300, credits=450)
        self.assertEqual(self.cul.frames, [])
        self.assertFalse(self.c._radio_requests)

    async def test_sent_request_finishes_before_new_temperature(self):
        self.worker()
        first = self.temperature(20)
        await self.settle()
        entry = next(iter(self.c._command_queue.entries.values()))
        self.assertTrue(entry.has_been_sent)
        with self.assertRaises(ValueError):
            self.c._command_queue.delete(entry.id)
        second = self.temperature(23)
        await self.settle()
        self.assertFalse(first.done())
        self.cul.feed(transport.ack_line(self.cul.frames[0]))
        await asyncio.wait_for(first, .5)
        await self.settle()
        self.assertEqual(len(self.cul.frames), 2)
        self.cul.feed(transport.ack_line(self.cul.frames[0]))
        await self.settle()
        self.assertFalse(second.done())
        self.cul.feed(transport.ack_line(self.cul.frames[1]))
        self.assertEqual((await asyncio.wait_for(second, .5)).status, "completed")

    async def test_write_lock_cancellation_boundary(self):
        self.worker()
        await self.c._send_lock.acquire()
        task = self.temperature(20)
        await self.settle()
        entry = next(iter(self.c._command_queue.entries.values()))
        self.c._command_queue.delete(entry.id)
        self.c._send_lock.release()
        self.assertEqual((await asyncio.wait_for(task, .5)).status, "cancelled")
        await self.settle()
        self.assertEqual(self.cul.frames, [])

    async def test_clear_does_not_cancel_protected_or_sent_entries(self):
        first = self.temperature(20)
        await self.settle()
        cmd = protocol.build_config_week_profile(10, self.c.own_address, 0x123456, 2, 0, "28" * 14)
        config = asyncio.create_task(self.c._send_command(cmd, expected_src="123456", device_address="123456",
            counter=10, description="ConfigWeekProfile", job_id="test-job"))
        self.tasks.append(config)
        await self.settle()
        cleared = self.c._command_queue.clear()
        self.assertEqual(len(cleared["removed"]), 1)
        self.assertEqual((await first).status, "cancelled")
        self.assertFalse(config.done())
        self.assertEqual(len(self.c._command_queue.entries), 1)

    async def test_high_frequency_does_not_leak_entries_or_counters(self):
        tasks = [self.temperature(10 + (n % 30) / 2, address=f"{1 + n % 4:06X}") for n in range(600)]
        await self.settle()
        self.assertEqual(len(self.c._command_queue.entries), 4)
        self.assertEqual(len(self.c._command_queue.history), 50)
        self.assertEqual(self.c._command_queue.superseded_count, 596)
        self.assertEqual(self.c._counter, 0)
        self.c._command_queue.clear()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 1)
        self.assertEqual(sum(result.status == "cancelled" for result in results), 4)
        self.assertFalse(self.c._command_queue.entries)

    async def test_reconnect_does_not_restore_superseded_request(self):
        self.cul.reply = False
        self.worker()
        old = self.temperature(20)
        await self.settle()
        self.cul.close()
        await self.settle()
        newest = self.temperature(23)
        await self.settle()
        self.assertEqual((await old).status, "superseded")
        self.attach(450)
        self.ack()
        await self.advance(10)
        await asyncio.wait_for(newest, .5)
        self.assertEqual(len(self.cul.frames), 1)
        self.assertEqual(bytes.fromhex(self.cul.frames[0][2:])[11] & 63, 46)

    async def test_snapshot_is_detached_and_filters_do_not_mutate_queue(self):
        task = self.temperature(20)
        await self.settle()
        data = api.queue_snapshot({"controller": self.c}, {"address": "123456", "scope": "general"})
        self.assertEqual(len(data["entries"]), 1)
        data["entries"][0]["status"] = "bad"
        self.assertEqual(next(iter(self.c._command_queue.entries.values())).status, "queued")
        self.assertEqual(api.queue_snapshot({"controller": self.c}, {"address": "FFFFFF"})["entries"], [])
        with self.assertRaises(ValueError):
            api.select_controller({"one": self.c, "two": self.c}, None)
        self.c._command_queue.clear()
        await task

    def persistent_storage(self):
        self.saved = None
        async def save(data):
            self.saved = copy.deepcopy(data)
        self.c._store = types.SimpleNamespace(async_save=save)
        self.c._save_devices = mod.CulMaxCoordinator._save_devices.__get__(self.c)

    async def test_cancelled_configuration_is_durable_and_not_restored(self):
        self.persistent_storage()
        self.c._devices["123456"] = mod.KnownDevice("123456", 1, "Bad", paired=True)
        commands = [mod.PendingClimateCommand("config_week_profile", f"Monday part {part}", day=2, part=part,
                                             chunk_hex="28" * (14 if part == 0 else 12)) for part in (0, 1)]
        await self.c._replace_pending_climate_commands("123456", commands)
        job_id = commands[0].job_id
        self.assertEqual(commands[1].job_id, job_id)
        with self.assertRaises(ValueError):
            await self.c.async_cancel_config_job(job_id, confirm=False)
        result = await self.c.async_cancel_config_job(job_id, confirm=True)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.saved["pending_climate_config"], {})
        restored = mod.CulMaxCoordinator(types.SimpleNamespace(loop=self.clock), "simulated")
        restored._store = types.SimpleNamespace(async_load=AsyncMock(return_value=self.saved), async_save=AsyncMock())
        restored._sync_device_registry_entry = AsyncMock()
        await restored._load_devices()
        self.assertFalse(restored._pending_climate_config)
        self.assertEqual(restored._config_jobs[job_id]["status"], "cancelled")

    async def test_configuration_cancel_finishes_active_step_only(self):
        self.persistent_storage()
        self.worker()
        self.c._devices["123456"] = mod.KnownDevice("123456", 1, "Bad", paired=True)
        commands = [mod.PendingClimateCommand("config_week_profile", f"Monday part {part}", day=2, part=part,
                                             chunk_hex="28" * (14 if part == 0 else 12)) for part in (0, 1)]
        await self.c._replace_pending_climate_commands("123456", commands)
        self.c._maybe_sync_time_after_climate_config = AsyncMock()
        task = asyncio.create_task(self.c._process_climate_config_queue("123456", trigger="test"))
        self.tasks.append(task)
        await asyncio.sleep(.12)
        await self.settle()
        self.assertEqual(len(self.cul.frames), 1)
        job_id = commands[0].job_id
        result = await self.c.async_cancel_config_job(job_id, confirm=True)
        self.assertEqual(result["status"], "cancelling")
        self.cul.feed(transport.ack_line(self.cul.frames[0]))
        await asyncio.wait_for(task, .5)
        self.assertEqual(len(self.cul.frames), 1)
        self.assertEqual(self.c._config_jobs[job_id]["status"], "cancelled")
        self.assertEqual(self.c._config_jobs[job_id]["confirmed_steps"], [commands[0].step_id])
        self.assertEqual(self.saved["pending_climate_config"], {})

    async def test_service_responses_and_batch_deletion(self):
        import sys
        from unittest.mock import patch
        callbacks = {}
        class ValidationError(ValueError):
            pass
        dr = types.ModuleType("homeassistant.helpers.device_registry")
        ha_entry = types.SimpleNamespace(name_by_user="HA Heizung", name="Default")
        dr.async_get = lambda hass: types.SimpleNamespace(async_get_device=lambda **kwargs: ha_entry)
        cv = types.ModuleType("homeassistant.helpers.config_validation")
        cv.string = str
        cv.boolean = bool
        cv.has_at_least_one_key = lambda *args: lambda value: value
        vol = types.ModuleType("voluptuous")
        for name in ("Schema", "All", "In", "Length", "Equal"):
            setattr(vol, name, lambda *args, **kwargs: lambda value: value)
        vol.Optional = vol.Required = lambda name: name
        vol.Exclusive = lambda name, group: name
        core = types.ModuleType("homeassistant.core")
        core.SupportsResponse = types.SimpleNamespace(ONLY="only", OPTIONAL="optional")
        exceptions = types.ModuleType("homeassistant.exceptions")
        exceptions.ServiceValidationError = ValidationError
        services = types.SimpleNamespace(has_service=lambda *args: False,
            async_register=lambda domain, name, handler, **kwargs: callbacks.update({name: handler}))
        hass = types.SimpleNamespace(data={api.CONTROLLERS: {"one": self.c}}, services=services)
        with patch.dict(sys.modules, {"voluptuous": vol, "homeassistant": types.ModuleType("homeassistant"),
                        "homeassistant.helpers": types.ModuleType("homeassistant.helpers"), "homeassistant.core": core,
                        "homeassistant.exceptions": exceptions, "homeassistant.helpers.config_validation": cv,
                        "homeassistant.helpers.device_registry": dr}):
            api.register_queue_services(hass)
        self.assertEqual(set(callbacks), set(api.SERVICES))
        task = self.temperature(20)
        await self.settle()
        entry = next(iter(self.c._command_queue.entries.values()))
        def call(service, data, response=True):
            return callbacks[service](types.SimpleNamespace(service=service, data=data, return_response=response))
        listed = await call("get_queue", {})
        self.assertEqual(listed["entries"][0]["id"], entry.id)
        self.assertEqual(listed["entries"][0]["device_name"], "HA Heizung")
        deleted = await call("delete_queue_entry", {"entry_ids": [entry.id, "missing"]})
        self.assertEqual(deleted["removed"], [entry.id])
        self.assertEqual(deleted["protected"][0]["id"], "missing")
        self.assertEqual((await task).status, "cancelled")
        with self.assertRaises(ValidationError):
            await call("delete_queue_entry", {"entry_id": "missing"})
        self.assertIsNone(await call("clear_queue", {}, False))

    async def test_final_write_guard_after_successful_query(self):
        self.worker()
        locked = asyncio.Event()
        release = asyncio.Event()
        async def hold_lock():
            async with self.c._send_lock:
                locked.set()
                await release.wait()
        hook_task = None
        def before_query_reply(cul):
            nonlocal hook_task
            if hook_task is None:
                hook_task = asyncio.create_task(hold_lock())
                self.tasks.append(hook_task)
        self.cul.query_hook = before_query_reply
        task = self.temperature(20)
        await asyncio.wait_for(locked.wait(), .5)
        await self.settle()
        entry = next(iter(self.c._command_queue.entries.values()))
        self.assertEqual(self.cul.commands, ["X"])
        self.c._command_queue.delete(entry.id)
        release.set()
        self.assertEqual((await asyncio.wait_for(task, .5)).status, "cancelled")
        await self.settle()
        self.assertEqual(self.cul.frames, [])

    async def test_invalid_new_intent_does_not_supersede_valid_one(self):
        old = self.temperature(20)
        await self.settle()
        invalid = self.temperature(float("nan"))
        with self.assertRaises(ValueError):
            await invalid
        self.assertFalse(old.done())
        self.assertEqual(len(self.c._command_queue.entries), 1)
        self.c._command_queue.clear()
        await old

    async def test_capacity_rejects_without_dropping_existing_commands(self):
        self.c._command_queue.capacity = 1
        first = self.temperature(20)
        await self.settle()
        second = self.temperature(21, "234567")
        with self.assertRaisesRegex(ValueError, "voll"):
            await second
        self.assertEqual(len(self.c._command_queue.entries), 1)
        self.assertFalse(first.done())
        self.c._command_queue.clear()
        await first

    async def test_legacy_configuration_migration_preserves_steps(self):
        self.persistent_storage()
        self.c._devices["123456"] = mod.KnownDevice("123456", 1, "Bad", paired=True)
        commands = [mod.PendingClimateCommand("config_week_profile", f"Monday part {part}", day=2, part=part,
                                             chunk_hex="28" * (14 if part == 0 else 12)) for part in (0, 1)]
        await self.c._replace_pending_climate_commands("123456", commands)
        legacy = copy.deepcopy(self.saved)
        legacy["schema_version"] = 2
        legacy.pop("configuration_jobs")
        for step in legacy["pending_climate_config"]["123456"]:
            step.pop("job_id")
            step.pop("step_id")
        saved = []
        restored = mod.CulMaxCoordinator(types.SimpleNamespace(loop=self.clock), "simulated")
        restored._store = types.SimpleNamespace(async_load=AsyncMock(return_value=legacy),
            async_save=AsyncMock(side_effect=lambda data: saved.append(copy.deepcopy(data))))
        restored._sync_device_registry_entry = AsyncMock()
        await restored._load_devices()
        steps = restored._pending_climate_config["123456"]
        self.assertEqual([step.chunk_hex for step in steps], [command.chunk_hex for command in commands])
        self.assertEqual(steps[0].job_id, steps[1].job_id)
        self.assertNotEqual(steps[0].step_id, steps[1].step_id)
        self.assertEqual(saved[-1]["schema_version"], 3)
        self.assertEqual(len(saved[-1]["configuration_jobs"]), 1)

    async def test_orphaned_replaced_configuration_metadata_is_bounded(self):
        self.c._devices["123456"] = mod.KnownDevice("123456", 1, "Bad", paired=True)
        for index in range(70):
            self.c._pending_shutter_config["123456"] = [mod.PendingShutterCommand("set_group_id", f"Group {index}", group_id=index)]
            self.c._ensure_config_jobs()
        self.assertLessEqual(len(self.c._config_jobs), 51)
        self.assertEqual(sum(job["status"] == "queued" for job in self.c._config_jobs.values()), 1)

    async def test_cancelled_time_burst_does_not_create_more_packets_or_success(self):
        self.c._devices["123456"] = mod.KnownDevice("123456", 1, "Bad", paired=True)
        self.cul.credits = 0
        self.worker()
        task = asyncio.create_task(self.c.async_send_time_information("123456"))
        self.tasks.append(task)
        await self.settle()
        self.c._command_queue.clear()
        self.assertEqual((await asyncio.wait_for(task, .5)).status, "cancelled")
        await self.advance(300, credits=450)
        self.assertFalse(self.cul.frames)
        self.assertEqual(self.c.get_device("123456").last_time_sync_at, "")
        self.assertFalse(self.c._command_queue.entries)
