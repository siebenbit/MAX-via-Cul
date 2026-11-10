"""Reported versus requested state using the production reader and simulated CUL."""
from __future__ import annotations

import asyncio
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

import test_credit as transport
import test_debounce as debounce

mod = transport.mod
protocol = transport.protocol
climate = debounce.climate
BASE = Path(__file__).parents[1]


class ClimateStateTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = debounce.DebounceTests.asyncSetUp
    asyncTearDown = debounce.DebounceTests.asyncTearDown
    attach = debounce.DebounceTests.attach
    settle = debounce.DebounceTests.settle
    advance = debounce.DebounceTests.advance
    request = debounce.DebounceTests.request
    entity = debounce.DebounceTests.entity

    def display(self, address="123456"):
        return self.c.get_display_state(address)

    async def report(self, temperature=20, mode=0, *, address="123456", valve=0,
                     kind=0x60, payload=None):
        if payload is None:
            payload = bytes([mode, valve, int(temperature * 2), 0, 190])
        body = (bytes([201, 0, kind]) + bytes.fromhex(address)
                + self.c.own_address.to_bytes(3, "big") + b"\x00" + payload)
        self.cul.feed("Z" + bytes([len(body)]).hex() + body.hex())
        await self.settle()

    async def complete(self, temperature=22, mode=1):
        task = self.request(temperature, mode=mode)
        await self.settle()
        await self.advance(2.01)
        await asyncio.wait_for(task, .5)
        return self.c.get_temperature_intent("123456")

    def assert_display(self, entity, temperature, hvac, preset="none"):
        self.assertEqual(entity._attr_target_temperature, temperature)
        self.assertEqual(entity._attr_hvac_mode, hvac)
        self.assertEqual(entity._attr_preset_mode, preset)
        self.assertIsNone(entity._attr_hvac_action)

    async def test_unsolicited_local_and_schedule_changes_update_without_sending(self):
        entity = await self.entity()
        await self.report(23, mode=1, valve=45)
        self.assert_display(entity, 23, "heat")
        self.assertEqual(entity.extra_state_attributes["valve_position"], 45)
        await self.report(17, mode=0, valve=0)
        self.assert_display(entity, 17, "auto")
        self.assertEqual(entity.extra_state_attributes["valve_position"], 0)
        self.assertEqual(self.display()["state_source"], "reported")
        self.assertFalse(self.cul.commands)

    async def test_delete_debouncing_rolls_back_temperature_mode_and_preset_to_latest_report(self):
        entity = await self.entity()
        task = self.request(22, mode=1)
        await self.settle()
        await self.report(18, mode=0, valve=10)
        self.assert_display(entity, 22, "heat")
        self.assertEqual(self.display()["reported_target_temperature"], 18)
        self.c.delete_queue_entry(self.c.get_temperature_intent("123456").entry.id)
        self.assertEqual((await task).status, "cancelled")
        self.assert_display(entity, 18, "auto")
        self.assertIsNone(self.display()["requested_mode"])
        self.assertEqual(self.display()["command_status"], "cancelled")
        self.assertFalse(self.cul.commands)

    async def test_delete_credit_waiting_boost_restores_latest_auto_state(self):
        entity = await self.entity()
        self.cul.credits = 0
        task = self.request(0, mode=3)
        await self.settle()
        await self.advance(2.01)
        self.assertEqual(self.display()["command_status"], "waiting_for_credits")
        await self.report(19, mode=0)
        self.assert_display(entity, 20, "heat", "boost")
        self.c.delete_queue_entry(self.c.get_temperature_intent("123456").entry.id)
        self.assertEqual((await task).status, "cancelled")
        self.assert_display(entity, 19, "auto")
        await self.advance(150)
        self.assertFalse(self.cul.frames)

    async def test_superseded_generation_cannot_rollback_newer_mode_or_temperature(self):
        entity = await self.entity()
        old = self.request(22, mode=1)
        await self.settle()
        new = self.request(18, mode=0)
        await self.settle()
        self.assertEqual((await old).status, "superseded")
        self.assert_display(entity, 18, "auto")
        self.assertEqual(self.display()["command_status"], "debouncing")
        self.c.clear_queue()
        await new

    async def test_replacement_does_not_publish_an_intermediate_reported_target(self):
        entity = await self.entity()
        older = self.request(22)
        await self.settle()
        newer = self.request(23, mode=0)
        await self.settle()
        self.assertEqual(entity.published, [22, 23])
        self.assertEqual((await older).status, "superseded")
        self.c.clear_queue()
        await newer

    async def test_temperature_edit_keeps_pending_mode_switch(self):
        entity = await self.entity()
        await self.report(20, mode=0)
        manual = asyncio.create_task(entity.async_set_hvac_mode(climate.HVACMode.HEAT))
        self.tasks.append(manual)
        await self.settle()
        changed = asyncio.create_task(entity.async_set_temperature(temperature=22))
        self.tasks.append(changed)
        await self.settle()
        self.assert_display(entity, 22, "heat")
        self.assertEqual(self.display()["requested_mode"], "manual")
        automatic = asyncio.create_task(entity.async_set_hvac_mode(climate.HVACMode.AUTO))
        self.tasks.append(automatic)
        await self.settle()
        later = asyncio.create_task(entity.async_set_temperature(temperature=23))
        self.tasks.append(later)
        await self.settle()
        self.assert_display(entity, 23, "auto")
        self.c.clear_queue()
        await asyncio.gather(manual, changed, automatic, later)

    async def test_ack_is_not_a_state_report_and_new_report_has_immediate_priority(self):
        entity = await self.entity()
        await self.complete()
        self.assertEqual(self.display()["command_status"], "acknowledged")
        self.assertEqual(self.display()["reported_target_temperature"], 20)
        self.assert_display(entity, 22, "heat")
        await self.report(18, mode=0)
        self.assert_display(entity, 18, "auto")
        self.assertEqual(self.display()["command_status"], "acknowledged")
        self.assertEqual(self.display()["state_source"], "reported")
        self.assertEqual(len(self.cul.frames), 1)

    async def test_matching_report_synchronizes_then_local_changes_take_immediate_priority(self):
        entity = await self.entity()
        intent = await self.complete()
        await self.report(22, mode=1, valve=30)
        self.assertEqual(self.display()["command_status"], "synchronized")
        self.assertFalse(intent.overlay)
        await self.report(18, mode=0)
        self.assert_display(entity, 18, "auto")
        await self.report(24, mode=1)
        self.assert_display(entity, 24, "heat")
        self.assertEqual(len(self.cul.frames), 1)

    async def test_matching_report_before_send_cannot_confirm_later_ack(self):
        await self.report(22, mode=1)
        await self.complete()
        self.assertEqual(self.display()["command_status"], "acknowledged")
        self.assertEqual(self.display()["state_source"], "acknowledged")

    async def test_matching_report_between_send_and_ack_is_retained(self):
        self.cul.frame_hook = None
        task = self.request(22)
        await self.settle()
        await self.advance(2.01)
        await self.report(22, mode=1)
        self.assertEqual(self.display()["command_status"], "awaiting_ack")
        self.cul.feed(transport.ack_line(self.cul.frames[-1]))
        await asyncio.wait_for(task, .5)
        self.assertEqual(self.display()["command_status"], "synchronized")

    async def test_ack_timeout_is_unconfirmed_until_a_real_report_arrives(self):
        entity = await self.entity()
        self.cul.frame_hook = None
        with patch.object(mod, "SET_TEMPERATURE_ACK_RETRIES", 0), patch.object(mod, "SET_TEMPERATURE_ACK_TIMEOUT", .01):
            task = self.request(22)
            await self.settle()
            await self.advance(2.01)
            outcome = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), .5)
            self.assertIsInstance(outcome[0], ConnectionError)
        self.assertEqual(self.display()["command_status"], "unconfirmed")
        self.assert_display(entity, 22, "heat")
        await self.advance(30.01)
        self.assert_display(entity, 22, "heat")
        self.assertEqual(self.display()["command_status"], "unconfirmed")
        await self.report(18, mode=0)
        self.assert_display(entity, 18, "auto")
        self.assertEqual(self.display()["command_status"], "unconfirmed")
        await self.report(22, mode=1)
        self.assertEqual(self.display()["command_status"], "synchronized")

    async def test_definite_firmware_rejection_rolls_back_without_unconfirmed_overlay(self):
        entity = await self.entity()
        await self.report(18, mode=0)
        self.cul.frame_hook = lambda cul, cmd: cul.feed("ZERR101")
        task = self.request(22)
        await self.settle()
        await self.advance(2.01)
        outcome = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), .5)
        self.assertIsInstance(outcome[0], ConnectionError)
        self.assert_display(entity, 18, "auto")
        self.assertEqual(self.display()["command_status"], "failed")
        self.assertFalse(self.c.get_temperature_intent("123456").overlay)

    async def test_failure_before_handoff_restores_reported_state(self):
        entity = await self.entity()
        await self.report(18, mode=0)
        with patch.object(self.c, "_send_command", AsyncMock(side_effect=ConnectionError("not connected"))):
            task = self.request(22)
            await self.settle()
            await self.advance(2.01)
            result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), .5)
        self.assertIsInstance(result[0], ConnectionError)
        self.assert_display(entity, 18, "auto")
        self.assertEqual(self.display()["command_status"], "failed")
        self.assertFalse(self.cul.frames)

    async def test_firmware_error_after_possible_frame_send_is_unconfirmed(self):
        self.cul.frame_hook = lambda cul, cmd: cul.feed("ZERR30D")
        task = self.request(22)
        await self.settle()
        await self.advance(2.01)
        result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), .5)
        self.assertIsInstance(result[0], ConnectionError)
        self.assertEqual(self.display()["command_status"], "unconfirmed")
        self.assertEqual(self.display()["target_temperature"], 22)

    async def test_rejected_retry_does_not_erase_earlier_possible_transmission(self):
        def frame_hook(cul, cmd):
            if len(cul.frames) == 2:
                cul.feed("ZERR101")
        self.cul.frame_hook = frame_hook
        with patch.object(mod, "SET_TEMPERATURE_ACK_TIMEOUT", .01):
            task = self.request(22)
            await self.settle()
            await self.advance(2.01)
            result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), .5)
        self.assertIsInstance(result[0], ConnectionError)
        self.assertEqual(len(self.cul.frames), 2)
        self.assertEqual(self.display()["command_status"], "unconfirmed")

    async def test_failure_after_possible_handoff_is_unconfirmed(self):
        entity = await self.entity()
        async def broken_write(cmd, *, before_send=None, entry=None, **kwargs):
            self.c._command_queue.before_write(entry)
            before_send()
            entry.may_have_transmitted = True
            raise ConnectionError("connection reset after write")
        with patch.object(self.c, "_send_raw", broken_write):
            task = self.request(22)
            await self.settle()
            await self.advance(2.01)
            result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), .5)
        self.assertIsInstance(result[0], ConnectionError)
        self.assert_display(entity, 22, "heat")
        self.assertEqual(self.display()["command_status"], "unconfirmed")
        await self.advance(30.01)
        self.assert_display(entity, 22, "heat")

    async def test_late_ack_for_older_command_does_not_confirm_newer_command(self):
        entity = await self.entity()
        self.cul.frame_hook = None
        older = self.request(21)
        await self.settle()
        await self.advance(2.01)
        old_frame = self.cul.frames[-1]
        newer = self.request(23, mode=0)
        await self.settle()
        self.cul.feed(transport.ack_line(old_frame))
        await asyncio.wait_for(older, .5)
        self.assertEqual(self.display()["command_status"], "debouncing")
        await self.advance(2.01)
        self.cul.feed(transport.ack_line(old_frame))
        await self.settle()
        self.assertEqual(self.display()["command_status"], "awaiting_ack")
        self.assert_display(entity, 23, "auto")
        self.cul.feed(transport.ack_line(self.cul.frames[-1]))
        await asyncio.wait_for(newer, .5)
        self.assertEqual(self.display()["command_status"], "acknowledged")

    async def test_partial_wall_control_preserves_mode_flags_until_and_valve_absence(self):
        device = self.c.get_device("123456")
        device.device_type = mod.DEVICE_WALL_THERMOSTAT
        device.last_state = {}
        entity = await self.entity()
        await self.report(kind=0x70, payload=bytes([0xA0, 1, 40]))
        self.assert_display(entity, 20, "auto")
        await self.report(kind=0x42, payload=bytes([44, 195]))
        self.assert_display(entity, 22, "auto")
        self.assertEqual(entity._attr_current_temperature, 19.5)
        self.assertTrue(device.last_state["panel_locked"])
        self.assertTrue(device.last_state["battery_low"])
        self.assertNotIn("valve_position", device.last_state)
        self.assertNotIn("reported_fields", device.last_state)
        self.assertFalse(self.cul.commands)

    async def test_incomplete_status_does_not_erase_measured_temperature(self):
        entity = await self.entity()
        await self.report(22, mode=0)
        await self.report(payload=bytes([1, 0, 44]))
        self.assertEqual(entity._attr_current_temperature, 19)
        self.assert_display(entity, 22, "heat")

    async def test_partial_wall_control_cannot_confirm_a_mode_not_reported_after_send(self):
        device = self.c.get_device("123456")
        device.device_type = mod.DEVICE_WALL_THERMOSTAT
        await self.complete()
        await self.report(kind=0x42, payload=bytes([44, 190]))
        self.assertEqual(self.display()["command_status"], "acknowledged")
        await self.report(kind=0x70, payload=bytes([1, 0, 44]))
        self.assertEqual(self.display()["command_status"], "synchronized")

    async def test_special_mode_report_missing_until_keeps_it_but_mode_change_clears_it(self):
        entity = await self.entity()
        until = datetime(2030, 2, 3, 12, 30)
        await self.report(payload=bytes([2, 0, 36]) + bytes.fromhex(protocol.encode_max_until_datetime(until)))
        await self.report(payload=bytes([2, 0, 38]))
        self.assertIsNotNone(self.display()["until"])
        self.assert_display(entity, 19, "heat", "away")
        await self.report(20, mode=0)
        self.assertIsNone(self.display()["until"])
        self.assert_display(entity, 20, "auto")

    async def test_frost_protection_remains_off_after_report_and_auto_minimum_remains_auto(self):
        entity = await self.entity()
        task = asyncio.create_task(entity.async_set_hvac_mode(climate.HVACMode.OFF))
        self.tasks.append(task)
        await self.settle()
        self.assert_display(entity, 4.5, "off")
        await self.advance(2.01)
        await asyncio.wait_for(task, .5)
        await self.report(4.5, mode=1)
        self.assert_display(entity, 4.5, "off")
        await self.report(4.5, mode=0)
        self.assert_display(entity, 4.5, "auto")

    async def test_reported_boost_and_holiday_have_consistent_presets(self):
        entity = await self.entity()
        await self.report(22, mode=3, valve=100)
        self.assert_display(entity, 22, "heat", "boost")
        until = datetime(2030, 2, 3, 12, 30)
        payload = bytes([2, 0, 36]) + bytes.fromhex(protocol.encode_max_until_datetime(until))
        await self.report(payload=payload)
        self.assert_display(entity, 18, "heat", "away")
        self.assertIn("away", entity._attr_preset_modes)
        changed = asyncio.create_task(entity.async_set_temperature(temperature=19))
        self.tasks.append(changed)
        await self.settle()
        self.assertEqual(self.c.get_temperature_intent("123456").until.timestamp(), until.timestamp())
        self.assert_display(entity, 19, "heat", "away")
        self.c.clear_queue()
        await changed

    async def test_ending_special_preset_selects_auto_without_inventing_temperature(self):
        entity = await self.entity()
        await self.report(22, mode=3)
        task = asyncio.create_task(entity.async_set_preset_mode("none"))
        self.tasks.append(task)
        await self.settle()
        self.assert_display(entity, 22, "auto")
        self.c.clear_queue()
        await task
        with self.assertRaisesRegex(ValueError, "until"):
            await entity.async_set_preset_mode("away")

    async def test_unknown_state_does_not_invent_mode_activity_or_temperature(self):
        self.c.get_device("123456").last_state = {}
        entity = await self.entity()
        self.assertIsNone(entity._attr_hvac_mode)
        self.assertIsNone(entity._attr_target_temperature)
        self.assertIsNone(entity._attr_hvac_action)
        self.assertFalse(entity._attr_available)
        with self.assertRaisesRegex(ValueError, "unbekannt"):
            await entity.async_set_hvac_mode(climate.HVACMode.HEAT)
        with self.assertRaisesRegex(ValueError, "unbekannt"):
            await entity.async_set_temperature(temperature=22)
        self.assertFalse(self.cul.commands)

    async def test_multiple_devices_remain_independent(self):
        first = self.request(22, mode=1)
        second = self.request(18, address="234567", mode=0)
        await self.settle()
        await self.report(17, mode=0)
        await self.report(24, mode=1, address="234567")
        self.c.delete_queue_entry(self.c.get_temperature_intent("123456").entry.id)
        await first
        self.assertEqual(self.display()["target_temperature"], 17)
        self.assertEqual(self.display("234567")["target_temperature"], 18)
        self.assertEqual(self.display("234567")["hvac_mode"], "auto")
        self.c.clear_queue()
        await second

    async def test_reconnect_retains_pending_display_and_cancellation_uses_newest_report(self):
        entity = await self.entity()
        self.cul.credits = 0
        task = self.request(22)
        await self.settle()
        await self.advance(2.01)
        old_reader = self.c._read_task
        await self.c._close_connection()
        await old_reader
        self.attach(credits=0)
        await self.report(18, mode=0)
        self.assert_display(entity, 22, "heat")
        self.c.clear_queue()
        self.assertEqual((await task).status, "cancelled")
        self.assert_display(entity, 18, "auto")
        self.assertFalse(self.cul.frames)

    async def test_acknowledged_state_does_not_revert_without_new_report(self):
        entity = await self.entity()
        await self.complete()
        self.assert_display(entity, 22, "heat")
        self.assertFalse(self.c.get_queue()["entries"])
        await self.advance(31)
        self.assert_display(entity, 22, "heat")
        await self.advance(3600)
        self.assert_display(entity, 22, "heat")
        self.assertEqual(self.display()["command_status"], "acknowledged")

    async def test_pure_manual_mode_change_stays_manual_without_new_report(self):
        entity = await self.entity()
        await self.report(20, mode=0)
        await self.complete(20, mode=1)
        await self.advance(3600)
        self.assert_display(entity, 20, "heat")
        self.assertEqual(self.display()["reported_mode"], "auto")
        self.assertEqual(self.display()["state_source"], "acknowledged")
        await self.report(20, mode=0)
        self.assert_display(entity, 20, "auto")

    async def test_deleting_newer_wish_keeps_previously_acknowledged_temperature_and_mode(self):
        entity = await self.entity()
        await self.report(18, mode=0)
        await self.complete(22, mode=1)
        task = self.request(24, mode=0)
        await self.settle()
        self.assert_display(entity, 24, "auto")
        self.c.clear_queue()
        self.assertEqual((await task).status, "cancelled")
        self.assert_display(entity, 22, "heat")
        self.assertEqual(self.display()["reported_target_temperature"], 18)
        self.assertEqual(self.display()["command_status"], "cancelled")

    async def test_partial_report_overrides_only_reported_acknowledged_fields(self):
        entity = await self.entity()
        device = self.c.get_device("123456")
        device.device_type = mod.DEVICE_WALL_THERMOSTAT
        await self.report(kind=0x70, payload=bytes([0, 0, 36]))
        await self.complete(22, mode=1)
        await self.report(kind=0x42, payload=bytes([46, 190]))
        self.assert_display(entity, 23, "heat")
        self.assertEqual(self.display()["reported_mode"], "auto")
        await self.report(kind=0x70, payload=bytes([0, 0, 46]))
        self.assert_display(entity, 23, "auto")
        self.assertEqual(self.display()["state_source"], "reported")
        self.assertEqual(len(self.cul.frames), 1)

    async def test_predecessor_ack_is_kept_if_newer_pending_wish_is_deleted(self):
        entity = await self.entity()
        self.cul.frame_hook = None
        older = self.request(22)
        await self.settle()
        await self.advance(2.01)
        newer = self.request(24, mode=0)
        await self.settle()
        self.cul.feed(transport.ack_line(self.cul.frames[0]))
        await asyncio.wait_for(older, .5)
        self.assert_display(entity, 24, "auto")
        self.c.clear_queue()
        self.assertEqual((await newer).status, "cancelled")
        self.assert_display(entity, 22, "heat")

    async def test_report_before_ack_does_not_overrule_later_command_acceptance(self):
        entity = await self.entity()
        self.cul.frame_hook = None
        task = self.request(22)
        await self.settle()
        await self.advance(2.01)
        await self.report(18, mode=0)
        self.cul.feed(transport.ack_line(self.cul.frames[0]))
        await asyncio.wait_for(task, .5)
        self.assert_display(entity, 22, "heat")
        await self.advance(3600)
        self.assert_display(entity, 22, "heat")
        await self.report(19, mode=0)
        self.assert_display(entity, 19, "auto")

    async def test_negative_ack_does_not_confirm_or_replace_accepted_state(self):
        entity = await self.entity()
        await self.complete(22)
        self.cul.frame_hook = lambda cul, cmd: cul.feed(transport.ack_line(cmd)[:-2] + "81")
        task = self.request(24, mode=0)
        await self.settle()
        await self.advance(2.01)
        result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), .5)
        self.assertIsInstance(result[0], ConnectionError)
        self.assertEqual(self.display()["command_status"], "failed")
        self.assert_display(entity, 22, "heat")
        self.assertEqual(len(self.cul.frames), 2)

    async def test_empty_ack_does_not_create_accepted_state(self):
        self.cul.frame_hook = lambda cul, cmd: cul.feed("Z0A" + transport.ack_line(cmd)[3:-2])
        with patch.object(mod, "SET_TEMPERATURE_ACK_RETRIES", 0), patch.object(mod, "SET_TEMPERATURE_ACK_TIMEOUT", .01):
            task = self.request(22)
            await self.settle()
            await self.advance(2.01)
            result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), .5)
        self.assertIsInstance(result[0], ConnectionError)
        self.assertEqual(self.display()["command_status"], "unconfirmed")
        self.assertFalse(self.c.get_device("123456").acknowledged_state)

    async def test_auto_without_explicit_target_does_not_retain_old_acknowledged_target(self):
        entity = await self.entity()
        await self.complete(22)
        await self.complete(0, mode=0)
        self.assertEqual(self.display()["mode"], 0)
        self.assertNotIn("desired_temperature", self.c.get_device("123456").acknowledged_state)
        await self.report(18, mode=0)
        self.assert_display(entity, 18, "auto")

    async def test_new_intent_takes_priority_over_old_acknowledged_state(self):
        entity = await self.entity()
        await self.complete()
        newer = self.request(23, mode=0)
        await self.settle()
        await self.report(22, mode=1)
        self.assert_display(entity, 23, "auto")
        self.assertEqual(self.display()["command_status"], "debouncing")
        self.c.clear_queue()
        await newer
        self.assert_display(entity, 22, "heat")

    async def test_acknowledged_state_has_no_pending_background_tasks_on_shutdown(self):
        intent = await self.complete()
        await self.c.async_shutdown()
        self.assertFalse(intent.overlay)
        self.assertFalse(self.c._temperature_tasks)

    async def test_restart_restores_reported_state_only_not_optimistic_or_ack_state(self):
        await self.complete()
        self.c._store = types.SimpleNamespace(async_save=AsyncMock())
        await mod.CulMaxCoordinator._save_devices(self.c)
        saved = self.c._store.async_save.call_args.args[0]
        self.assertEqual(saved["devices"]["123456"]["last_state"]["desired_temperature"], 20)
        self.assertNotIn("acknowledged_state", saved["devices"]["123456"])
        fresh = mod.CulMaxCoordinator(types.SimpleNamespace(loop=self.clock), "simulated")
        fresh._store = types.SimpleNamespace(async_load=AsyncMock(return_value=saved))
        fresh._save_devices = AsyncMock()
        fresh._sync_device_registry_entry = AsyncMock()
        await fresh._load_devices()
        self.assertEqual(fresh.get_display_state("123456")["target_temperature"], 20)
        self.assertEqual(fresh.get_display_state("123456")["state_source"], "reported")
        self.assertIsNone(fresh.get_temperature_intent("123456"))

    async def test_restart_discards_legacy_fabricated_wall_state(self):
        saved = {"schema_version": mod.STORAGE_SCHEMA_VERSION, "devices": {
            "123456": {"address": "123456", "device_type": mod.DEVICE_WALL_THERMOSTAT,
                       "name": "Wall", "last_state": {"mode": 1, "valve_position": 0,
                                                       "desired_temperature": 20}}
        }}
        self.c._store = types.SimpleNamespace(async_load=AsyncMock(return_value=saved))
        self.c._sync_device_registry_entry = AsyncMock()
        await self.c._load_devices()
        self.assertIsNone(self.display()["mode"])
        self.assertEqual(self.display()["target_temperature"], 20)
        self.assertNotIn("valve_position", self.display()["reported"])

    async def test_valve_sensor_keeps_real_zero_and_report_timestamp(self):
        # Load only HA's entity surfaces; exercise the real sensor implementation.
        modules = {name: types.ModuleType(name) for name in (
            "homeassistant", "homeassistant.components", "homeassistant.components.sensor",
            "homeassistant.const", "homeassistant.core", "homeassistant.helpers",
            "homeassistant.helpers.entity", "homeassistant.helpers.entity_platform",
            "homeassistant.helpers.event", "homeassistant.util", "homeassistant.util.dt")}
        sensor_api = modules["homeassistant.components.sensor"]
        sensor_api.SensorEntity = object
        sensor_api.SensorDeviceClass = types.SimpleNamespace(TIMESTAMP="timestamp")
        sensor_api.SensorStateClass = types.SimpleNamespace(MEASUREMENT="measurement", TOTAL_INCREASING="total_increasing")
        modules["homeassistant.const"].UnitOfTemperature = types.SimpleNamespace(CELSIUS="°C")
        modules["homeassistant.const"].EntityCategory = types.SimpleNamespace(DIAGNOSTIC="diagnostic")
        modules["homeassistant.core"].HomeAssistant = object
        modules["homeassistant.core"].callback = lambda func: func
        modules["homeassistant.helpers.entity"].DeviceInfo = lambda **kwargs: kwargs
        modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = object
        modules["homeassistant.helpers.event"].async_track_time_interval = lambda *args: None
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("_cul_budget_tests.sensor", BASE / "sensor.py")
            sensors = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(sensors)
        sensor = sensors.CulMaxValvePositionSensor(self.c, self.c.get_device("123456"))
        self.assertIsNone(sensor.native_value)
        await self.report(22, valve=0)
        self.assertEqual(sensor.native_value, 0)
        timestamp = sensor.extra_state_attributes["last_reported_at"]
        self.assertIsNotNone(timestamp)
        await self.report(payload=bytes([0, 1, 40]), kind=0x70)
        self.assertEqual(sensor.extra_state_attributes["last_reported_at"], timestamp)

    async def test_native_temperature_api_avoids_all_deprecated_temperature_members(self):
        native = debounce.load_climate(native=True)
        entity = native.CulMaxClimate(self.c, self.c.get_device("123456"))
        await entity.async_added_to_hass()
        task = self.request(22)
        await self.settle()
        self.assertEqual(entity._attr_native_temperature_unit, "°C")
        self.assertEqual(entity._attr_native_target_temperature, 22)
        self.assertEqual(entity._attr_native_current_temperature, 19)
        self.assertNotIn("_attr_temperature_unit", native.CulMaxClimate.__dict__)
        self.c.clear_queue()
        await task
        self.assertEqual(entity._attr_native_target_temperature, 20)


class ClimateTranslationsTests(unittest.TestCase):
    def test_manual_label_is_entity_specific_and_protocol_mode_is_unchanged(self):
        translations = json.loads((BASE / "translations/de.json").read_text())
        entity = translations["entity"]["climate"]["thermostat"]
        self.assertEqual(entity["state"]["heat"], "Manuell")
        self.assertEqual(entity["state"]["auto"], "Automatik")
        self.assertNotIn("entity_component", translations)
        self.assertEqual(climate.CulMaxClimate._attr_translation_key, "thermostat")
        self.assertEqual(str(climate.HVACMode.HEAT), "heat")

