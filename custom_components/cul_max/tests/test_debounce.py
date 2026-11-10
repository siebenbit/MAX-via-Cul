"""Trailing-edge deadlines and optimistic climate state using simulated transport."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from enum import IntFlag, StrEnum
from unittest.mock import patch

import test_credit as transport

mod = transport.mod


def load_climate():
    class Mode(StrEnum):
        AUTO = "auto"
        HEAT = "heat"
        OFF = "off"
    class Action(StrEnum):
        IDLE = "idle"
        HEATING = "heating"
    class Feature(IntFlag):
        TARGET_TEMPERATURE = 1
        PRESET_MODE = 2
        TURN_OFF = 4
        TURN_ON = 8
    class Entity:
        def async_on_remove(self, unsubscribe):
            self._removers = getattr(self, "_removers", []) + [unsubscribe]
        def async_write_ha_state(self):
            self.published = getattr(self, "published", []) + [self._attr_target_temperature]
    climate = types.ModuleType("homeassistant.components.climate")
    climate.ClimateEntity = Entity
    climate.ClimateEntityFeature = Feature
    climate.HVACMode = Mode
    climate.HVACAction = Action
    const = types.ModuleType("homeassistant.const")
    const.ATTR_TEMPERATURE = "temperature"
    const.UnitOfTemperature = types.SimpleNamespace(CELSIUS="°C")
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.callback = lambda method: method
    entity = types.ModuleType("homeassistant.helpers.entity")
    entity.DeviceInfo = lambda **kwargs: kwargs
    platform = types.ModuleType("homeassistant.helpers.entity_platform")
    platform.AddEntitiesCallback = object
    sys.modules["_cul_budget_tests"].CulMaxConfigEntry = object
    stubs = {"homeassistant": types.ModuleType("homeassistant"),
        "homeassistant.components": types.ModuleType("homeassistant.components"),
        "homeassistant.components.climate": climate, "homeassistant.const": const,
        "homeassistant.core": core, "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.entity": entity, "homeassistant.helpers.entity_platform": platform}
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("_cul_budget_tests.climate", Path(__file__).parents[1] / "climate.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


climate = load_climate()


class DebounceTests(unittest.IsolatedAsyncioTestCase):
    attach = transport.CreditTests.attach
    settle = transport.CreditTests.settle
    asyncTearDown = transport.CreditTests.asyncTearDown

    async def asyncSetUp(self):
        await transport.CreditTests.asyncSetUp(self)
        self.waiters = []
        async def wait_deadline(intent):
            while self.clock.time() < intent.deadline:
                event = asyncio.Event()
                waiter = (intent.deadline, event)
                self.waiters.append(waiter)
                try:
                    await event.wait()
                finally:
                    self.waiters.remove(waiter)
        self.c._wait_temperature_deadline = wait_deadline
        self.c._command_worker_task = asyncio.create_task(self.c._command_worker())
        self.cul.frame_hook = lambda cul, cmd: cul.feed(transport.ack_line(cmd))
        for address in ("123456", "234567"):
            self.c._devices[address] = mod.KnownDevice(address, 1, address, paired=True,
                last_state={"desired_temperature": 20.0, "measured_temperature": 19.0, "mode": 1})

    def request(self, temperature, address="123456", mode=1, until=None):
        task = asyncio.create_task(self.c.async_set_temperature(address, temperature, mode, until))
        self.tasks.append(task)
        return task

    async def advance(self, seconds):
        self.clock.offset += seconds
        for deadline, event in list(self.waiters):
            if self.clock.time() >= deadline:
                event.set()
        self.c._radio_changed.set()
        self.c._command_queue._ready.set()
        await self.settle()
        await self.settle()

    async def entity(self):
        entity = climate.CulMaxClimate(self.c, self.c.get_device("123456"))
        await entity.async_added_to_hass()
        return entity

    async def test_single_request_has_no_queue_or_rf_work_before_two_seconds(self):
        task = self.request(21)
        await self.settle()
        preview = self.c.get_queue()["entries"][0]
        self.assertEqual(preview["status"], "debouncing")
        self.assertEqual(self.c._temperature_debounce_seconds, 2.0)
        self.assertFalse(self.c._command_queue.entries)
        self.assertFalse(self.c._radio_requests)
        self.assertEqual(self.c._counter, 0)
        self.assertEqual(self.cul.commands, [])
        await self.advance(1.9)
        self.assertEqual(self.cul.commands, [])
        await self.advance(.11)
        self.assertEqual((await asyncio.wait_for(task, .5)).status, "completed")
        self.assertEqual(self.c._command_queue.history[-1]["id"], preview["id"])
        self.assertEqual(len(self.cul.frames), 1)

    async def test_change_at_one_point_nine_restarts_the_complete_deadline(self):
        old = self.request(20.5)
        await self.settle()
        await self.advance(1.9)
        newest = self.request(22)
        await self.settle()
        self.assertEqual((await old).status, "superseded")
        await self.advance(.11)
        self.assertFalse(self.cul.commands)
        await self.advance(1.78)
        self.assertFalse(self.cul.commands)
        await self.advance(.12)
        await asyncio.wait_for(newest, .5)
        self.assertEqual(len(self.cul.frames), 1)
        self.assertEqual(bytes.fromhex(self.cul.frames[0][2:])[11] & 63, 44)

    async def test_devices_have_independent_deadlines(self):
        a = self.request(21)
        await self.settle()
        await self.advance(1)
        b = self.request(22, address="234567")
        await self.settle()
        await self.advance(1.01)
        self.assertEqual((await asyncio.wait_for(a, .5)).status, "completed")
        self.assertFalse(b.done())
        await self.advance(1)
        await asyncio.wait_for(b, .5)
        self.assertEqual(len(self.cul.frames), 2)

    async def test_new_intent_immediately_supersedes_credit_waiter(self):
        self.cul.credits = 0
        old = self.request(21)
        await self.settle()
        await self.advance(2.01)
        self.assertEqual(next(iter(self.c._command_queue.entries.values())).status, "waiting_for_credits")
        new = self.request(23)
        await self.settle()
        self.assertEqual((await old).status, "superseded")
        self.assertFalse(self.c._command_queue.entries)
        self.cul.credits = 450
        await self.advance(1)
        self.assertFalse(self.cul.frames)
        await self.advance(1.01)
        await asyncio.wait_for(new, .5)
        self.assertEqual(len(self.cul.frames), 1)

    async def test_delete_and_clear_stop_timers_without_late_reappearance(self):
        first, second = self.request(21), self.request(22, address="234567")
        await self.settle()
        entry_id = self.c.get_temperature_intent("123456").entry.id
        self.c.delete_queue_entry(entry_id)
        self.assertEqual((await first).status, "cancelled")
        result = self.c.clear_queue("234567")
        self.assertEqual(len(result["removed"]), 1)
        self.assertEqual((await second).status, "cancelled")
        await self.advance(10)
        self.assertFalse(self.cul.commands)
        self.assertFalse(self.c._temperature_tasks)
        self.assertFalse(self.c.get_queue()["entries"])

    async def test_shutdown_finishes_pending_callers_and_does_not_restore_timers(self):
        task = self.request(21)
        await self.settle()
        await self.c.async_shutdown()
        self.assertEqual((await asyncio.wait_for(task, .5)).status, "cancelled")
        self.assertFalse(self.c._temperature_tasks)
        self.assertFalse(self.c._debounce_intents)
        self.assertFalse(self.cul.frames)

    async def test_rapid_plus_clicks_publish_each_desired_value_immediately(self):
        entity = await self.entity()
        calls = []
        for _ in range(4):
            value = entity._attr_target_temperature + .5
            calls.append(asyncio.create_task(entity.async_set_temperature(temperature=value)))
            self.tasks.append(calls[-1])
            await self.settle()
            self.assertEqual(entity._attr_target_temperature, value)
        self.assertEqual(entity._attr_target_temperature, 22)
        self.assertEqual(self.c.get_device("123456").last_state["desired_temperature"], 20)
        self.assertFalse(self.cul.commands)
        await self.advance(2.01)
        await asyncio.wait_for(asyncio.gather(*calls), .5)
        self.assertEqual(len(self.cul.frames), 1)

    async def test_old_reports_and_older_ack_do_not_overwrite_latest_desire(self):
        entity = await self.entity()
        self.cul.frame_hook = None
        old = self.request(21)
        await self.settle()
        await self.advance(2.01)
        newer = self.request(23)
        await self.settle()
        report = types.SimpleNamespace(mode=1, desired_temperature=20, measured_temperature=19, valve_position=0)
        entity._on_message(None, report)
        self.assertEqual(entity._attr_target_temperature, 23)
        self.cul.feed(transport.ack_line(self.cul.frames[0]))
        await asyncio.wait_for(old, .5)
        self.assertEqual(entity._attr_target_temperature, 23)
        self.c.delete_queue_entry(self.c.get_temperature_intent("123456").entry.id)
        self.assertEqual((await newer).status, "cancelled")
        self.assertEqual(entity._attr_target_temperature, 20)

    async def test_mode_and_until_are_kept_with_the_latest_intent(self):
        from datetime import datetime
        entity = await self.entity()
        until = datetime(2030, 2, 3, 12, 30)
        vacation = self.request(18, mode=2, until=until)
        await self.settle()
        changed = asyncio.create_task(entity.async_set_temperature(temperature=19))
        self.tasks.append(changed)
        await self.settle()
        self.assertEqual((await vacation).status, "superseded")
        latest = self.c.get_temperature_intent("123456")
        self.assertEqual((latest.mode, latest.until), (2, until))
        boost = self.request(0, mode=3)
        await self.settle()
        self.assertEqual(entity._attr_target_temperature, 19)
        self.assertEqual(entity._attr_preset_mode, "boost")
        automatic = self.request(0, mode=0)
        await self.settle()
        self.assertEqual((await boost).status, "superseded")
        self.assertEqual(entity._attr_target_temperature, 19)
        self.assertEqual(entity._attr_hvac_mode, "auto")
        await self.advance(2.01)
        await asyncio.wait_for(automatic, .5)
        await asyncio.wait_for(changed, .5)
        self.assertEqual(len(self.cul.frames), 1)
        self.assertEqual(bytes.fromhex(self.cul.frames[0][2:])[11], 0)

    async def test_configuration_prerequisite_does_not_block_the_command_worker(self):
        prerequisite = self.clock.create_future()
        self.c._pending_climate_tasks["123456"] = prerequisite
        temperature = self.request(21)
        await self.settle()
        await self.advance(2.01)
        self.assertTrue(self.c._command_queue.entries)
        self.assertFalse(self.cul.frames)
        command = transport.protocol.build_time_information(10, self.c.own_address, 0x234567)
        other = asyncio.create_task(self.c._send_command(command, expected_src=None,
            device_address="234567", counter=None, description="TimeInformation"))
        self.tasks.append(other)
        await asyncio.wait_for(other, .5)
        self.assertEqual(len(self.cul.frames), 1)
        prerequisite.set_result(None)
        await self.settle()
        await asyncio.wait_for(temperature, .5)
        self.assertEqual(len(self.cul.frames), 2)
        self.c._pending_climate_tasks.pop("123456")

    async def test_real_sleep_uses_the_two_second_trailing_deadline(self):
        self.c._wait_temperature_deadline = mod.CulMaxCoordinator._wait_temperature_deadline.__get__(self.c)
        started = self.clock.time()
        task = self.request(21)
        await self.settle()
        await asyncio.sleep(.03)
        self.assertFalse(self.cul.commands)
        await asyncio.wait_for(task, 3)
        self.assertGreaterEqual(self.clock.time() - started, 2)
        self.assertEqual(len(self.cul.frames), 1)

    async def test_failed_send_restores_reported_state_without_false_success(self):
        entity = await self.entity()
        self.cul.frame_hook = lambda cul, cmd: cul.feed("ZERR101")
        task = self.request(23)
        await self.settle()
        self.assertEqual(entity._attr_target_temperature, 23)
        await self.advance(2.01)
        outcome = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), .5)
        self.assertIsInstance(outcome[0], ConnectionError)
        self.assertEqual(self.c.get_temperature_intent("123456").entry.status, "failed")
        self.assertEqual(entity._attr_target_temperature, 20)

    async def test_post_ack_report_becomes_authoritative(self):
        entity = await self.entity()
        task = self.request(23)
        await self.settle()
        await self.advance(2.01)
        await asyncio.wait_for(task, .5)
        self.assertEqual(entity._attr_target_temperature, 23)
        report = types.SimpleNamespace(mode=0, desired_temperature=21, measured_temperature=19, valve_position=0)
        entity._on_message(None, report)
        self.assertEqual(entity._attr_target_temperature, 21)
        self.assertEqual(entity._attr_hvac_mode, "auto")
        self.assertFalse(self.c.get_temperature_intent("123456").overlay)

    async def test_deleting_exactly_at_handoff_removes_same_id(self):
        task = self.request(23)
        await self.settle()
        entry_id = self.c.get_queue()["entries"][0]["id"]
        # Give the timer its deadline, then delete synchronously before it resumes.
        self.clock.offset += 2.01
        for _, event in list(self.waiters):
            event.set()
        self.c.delete_queue_entry(entry_id)
        self.assertEqual((await asyncio.wait_for(task, .5)).status, "cancelled")
        await self.settle()
        self.assertFalse(self.cul.frames)

    async def test_configuration_deadline_expires_without_waiting_for_entire_profile(self):
        prerequisite = self.clock.create_future()
        self.c._pending_climate_tasks["123456"] = prerequisite
        task = self.request(21)
        await self.settle()
        await self.advance(2.01)
        self.assertFalse(self.cul.frames)
        await self.advance(8.01)
        self.assertEqual((await asyncio.wait_for(task, .5)).status, "completed")
        self.assertFalse(prerequisite.done())
        prerequisite.set_result(None)
        self.c._pending_climate_tasks.pop("123456")

    async def test_shutdown_of_already_queued_intent_returns_cancelled_result(self):
        self.cul.credits = 0
        task = self.request(23)
        await self.settle()
        await self.advance(2.01)
        self.assertTrue(self.c._command_queue.entries)
        await self.c.async_shutdown()
        self.assertEqual((await asyncio.wait_for(task, .5)).status, "cancelled")
        self.assertFalse(self.c._temperature_tasks)

    async def test_many_replacements_keep_only_one_timer_per_device(self):
        callers = [self.request(20 + (index % 4) / 2,
                    address="123456" if index % 2 else "234567") for index in range(300)]
        await self.settle()
        await self.settle()
        self.assertEqual(len(self.c._debounce_intents), 2)
        self.assertEqual(len(self.c._temperature_tasks), 2)
        self.assertEqual(len(self.waiters), 2)
        self.assertEqual(len(self.c._command_queue.history), 50)
        self.assertEqual(self.c._counter, 0)
        self.assertFalse(self.cul.commands)
        self.c.clear_queue()
        results = await asyncio.wait_for(asyncio.gather(*callers), 1)
        self.assertEqual(sum(result.status == "cancelled" for result in results), 2)
        await self.settle()
        self.assertFalse(self.c._temperature_tasks)
        self.assertFalse(self.waiters)

    async def test_preview_service_filter_and_id_survive_admission(self):
        import importlib
        api = importlib.import_module("_cul_budget_tests.queue_api")
        self.cul.credits = 0
        task = self.request(21)
        await self.settle()
        data = api.queue_snapshot({"controller": self.c}, {"statuses": ["debouncing"]})
        self.assertEqual(len(data["entries"]), 1)
        entry_id = data["entries"][0]["id"]
        self.assertTrue(self.c.has_queue_entry(entry_id))
        await self.advance(2.01)
        self.assertIn(entry_id, self.c._command_queue.entries)
        self.assertEqual(api.queue_snapshot({"controller": self.c}, {"statuses": ["debouncing"]})["entries"], [])
        self.c.delete_queue_entry(entry_id)
        self.assertEqual((await asyncio.wait_for(task, .5)).status, "cancelled")
