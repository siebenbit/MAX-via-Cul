"""Radio-saving regressions using the production single-reader transport."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
import unittest

import test_credit as transport

mod = transport.mod
protocol = transport.protocol


class TrafficTests(unittest.IsolatedAsyncioTestCase):
    attach = transport.CreditTests.attach
    send = transport.CreditTests.send
    settle = transport.CreditTests.settle
    advance = transport.CreditTests.advance
    asyncTearDown = transport.CreditTests.asyncTearDown

    async def asyncSetUp(self):
        await transport.CreditTests.asyncSetUp(self)
        for address in ("123456", "234567"):
            self.c._devices[address] = mod.KnownDevice(address, 1, address, paired=True)
        self.c._command_worker_task = asyncio.create_task(self.c._command_worker())

    def time(self, address="123456", **kwargs):
        task = asyncio.create_task(self.c.async_send_time_information(address, **kwargs))
        self.tasks.append(task)
        return task

    def stats(self, kind):
        return self.c.get_budget_diagnostics()["traffic_by_command"][kind]

    async def test_time_sync_uses_one_packet_and_112_credits(self):
        result = await asyncio.wait_for(self.time(), .5)
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(self.cul.frames), 1)
        self.assertEqual(self.stats("TimeInformation")["packets"], 1)
        self.assertEqual(self.stats("TimeInformation")["estimated_credits"], 112)
        self.assertTrue(self.cul.frames[0].startswith("Zs"))
        self.assertFalse(self.c._time_sync_requests)
        await self.settle()
        self.assertFalse(self.c._time_sync_tasks)

    async def test_overlapping_time_calls_share_pending_packet(self):
        self.cul.credits = 0
        first = self.time(automatic=True)
        await self.settle()
        second = self.time(automatic=True)
        third = self.time()
        await self.settle()
        self.assertEqual(len(self.c._command_queue.entries), 1)
        self.assertEqual(len(self.c._time_sync_tasks), 1)
        await self.advance(120, credits=450)
        results = await asyncio.wait_for(asyncio.gather(first, second, third), .5)
        self.assertTrue(all(item.status == "completed" for item in results))
        self.assertEqual(len(self.cul.frames), 1)

    async def test_protocol_request_protects_shared_pending_sync(self):
        self.cul.credits = 0
        normal = self.time()
        await self.settle()
        response = self.time(protocol_response=True)
        await self.settle()
        entry = next(iter(self.c._command_queue.entries.values()))
        self.assertTrue(entry.protected)
        self.assertFalse(entry.cancellable)
        self.assertEqual(self.c.clear_queue()["removed"], [])
        await self.advance(120, credits=450)
        await asyncio.wait_for(asyncio.gather(normal, response), .5)
        self.assertEqual(len(self.cul.frames), 1)

    async def test_auto_cooldown_does_not_suppress_manual_or_device_requests(self):
        await self.time()
        result = await self.time(automatic=True)
        self.assertEqual(result.status, "skipped")
        await self.time()
        await self.time(protocol_response=True)
        self.assertEqual(len(self.cul.frames), 3)
        await self.advance(61, credits=450)
        self.assertEqual((await self.time(automatic=True)).status, "completed")
        self.assertEqual(len(self.cul.frames), 4)

    async def test_fresh_protocol_request_after_write_gets_new_packet(self):
        first_written = asyncio.Event()
        self.cul.frame_hook = lambda cul, cmd: first_written.set()
        first = self.time()
        await asyncio.wait_for(first_written.wait(), .5)
        # Start the new request synchronously, before the existing barrier completes.
        second = self.time(protocol_response=True)
        await asyncio.wait_for(asyncio.gather(first, second), .5)
        self.assertEqual(len(self.cul.frames), 2)

    async def test_other_devices_are_not_coalesced(self):
        await asyncio.wait_for(asyncio.gather(self.time(), self.time("234567")), .5)
        self.assertEqual(len(self.cul.frames), 2)

    async def test_cancelled_waiter_does_not_cancel_shared_sync(self):
        self.cul.credits = 0
        first = self.time()
        await self.settle()
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        second = self.time()
        await self.advance(120, credits=450)
        await asyncio.wait_for(second, .5)
        self.assertEqual(len(self.cul.frames), 1)

    async def test_manual_queue_deletion_completes_all_waiters(self):
        self.cul.credits = 0
        first = self.time()
        await self.settle()
        second = self.time()
        await self.settle()
        self.c.clear_queue()
        results = await asyncio.wait_for(asyncio.gather(first, second), .5)
        self.assertEqual([item.status for item in results], ["cancelled", "cancelled"])
        await self.advance(120, credits=450)
        self.assertFalse(self.cul.frames)
        self.assertFalse(self.c._time_sync_requests)

    async def test_periodic_and_startup_dont_repeat_a_recent_runtime_sync(self):
        for device in self.c._devices.values():
            device.time_slot = datetime.now().astimezone().hour % 12
        self.c._ensure_time_slots_assigned = AsyncMock()
        original_sleep = mod.asyncio.sleep
        async def immediate_sleep(_delay):
            await original_sleep(0)
        with patch.object(mod.asyncio, "sleep", immediate_sleep):
            await self.c._run_periodic_time_sync()
            self.assertEqual(len(self.cul.frames), 2)
            await self.c._startup_time_sync_once()
            self.assertEqual(len(self.cul.frames), 2)

    async def test_persisted_time_does_not_suppress_startup_after_ha_restart(self):
        for device in self.c._devices.values():
            device.last_time_sync_at = datetime.now(UTC).isoformat()
        original_sleep = mod.asyncio.sleep
        async def immediate_sleep(_delay):
            await original_sleep(0)
        with patch.object(mod.asyncio, "sleep", immediate_sleep):
            await self.c._startup_time_sync_once()
        self.assertEqual(len(self.cul.frames), 2)

    async def test_auto_followup_only_for_unknown_stale_or_incorrect_clock(self):
        device = self.c.get_device("123456")
        device.last_time_sync_at = datetime.now(UTC).isoformat()
        send = AsyncMock(return_value=mod.CommandResult("completed"))
        original = self.c.async_send_time_information
        self.c.async_send_time_information = send
        try:
            with patch.object(mod, "AUTO_MODE_TIME_SYNC_FOLLOWUP_DELAY", 0):
                await self.c._auto_mode_time_sync_followup("123456")
                send.assert_not_awaited()
                device.last_time_sync_at = ""
                await self.c._auto_mode_time_sync_followup("123456")
                self.assertEqual(send.await_count, 1)
                device.last_time_sync_at = (datetime.now(UTC) - timedelta(hours=7)).isoformat()
                await self.c._auto_mode_time_sync_followup("123456")
                self.assertEqual(send.await_count, 2)
                device.last_time_sync_at = datetime.now(UTC).isoformat()
                device.last_time_offset_seconds = -8
                await self.c._auto_mode_time_sync_followup("123456")
                self.assertEqual(send.await_count, 3)
        finally:
            self.c.async_send_time_information = original

    async def test_time_payload_is_refreshed_after_budget_wait(self):
        self.cul.credits = 0
        task = self.time()
        await self.settle()
        moment = datetime(2030, 4, 5, 12, 34, 56, tzinfo=UTC)
        original = mod.build_time_information
        with patch.object(mod, "build_time_information", side_effect=lambda counter, src, dst: original(counter, src, dst, when=moment)):
            await self.advance(120, credits=450)
            await asyncio.wait_for(task, .5)
        self.assertEqual(bytes.fromhex(self.cul.frames[0][2:])[11:], bytes.fromhex("1E050C6238"))

    async def prepare_retry_race(self):
        old = self.cul
        old.frame_hook = lambda cul, cmd: setattr(cul, "reply", False)
        with patch.object(mod, "CUL_CREDIT_QUERY_TIMEOUT", .01):
            task = asyncio.create_task(self.c._send_command(self.cmd, expected_src="123456", device_address=None,
                counter=7, description="SetTemperature", timeout=12, retries=0))
            self.tasks.append(task)
            # Replace the stream only after the failed post-write barrier has
            # closed it and scheduled retry. A fixed sleep can race under load.
            async def failed_barrier():
                while not old.closed or self.c._credit_retry_at <= self.clock.time():
                    await asyncio.sleep(.001)
            await asyncio.wait_for(failed_barrier(), 1)
        self.attach(450)
        return task, old

    async def test_ack_arriving_during_retry_credit_query_prevents_rf_write(self):
        task, old = await self.prepare_retry_race()
        self.cul.query_hook = lambda cul: cul.feed(transport.ack_line(self.cmd))
        await self.advance(5.1)
        result = await asyncio.wait_for(task, .5)
        self.assertEqual(result.counter, 7)
        self.assertEqual(len(old.frames), 1)
        self.assertEqual(self.cul.frames, [])
        self.assertEqual(self.stats("SetTemperature")["packets"], 1)
        self.assertEqual(self.stats("SetTemperature")["retries"], 0)

    async def test_ack_arriving_while_retry_waits_for_write_lock_prevents_rf_write(self):
        task, old = await self.prepare_retry_race()
        locked, release = asyncio.Event(), asyncio.Event()
        async def hold():
            async with self.c._send_lock:
                locked.set()
                await release.wait()
        def hook(cul):
            held = asyncio.create_task(hold())
            self.tasks.append(held)
        self.cul.query_hook = hook
        await self.advance(5.1)
        await asyncio.wait_for(locked.wait(), .5)
        self.cul.feed(transport.ack_line(self.cmd))
        await self.settle()
        release.set()
        await asyncio.wait_for(task, .5)
        self.assertEqual(len(old.frames), 1)
        self.assertFalse(self.cul.frames)
        self.assertEqual(self.stats("SetTemperature")["packets"], 1)

    async def test_ack_matching_checks_actual_destination(self):
        future = self.clock.create_future()
        self.c._pending_ack = mod.PendingAck(7, "123456", future, "probe", expected_dst="654321")
        wrong = transport.ack_line(self.cmd)
        self.cul.feed(wrong)
        await self.settle()
        self.assertFalse(future.done())
        self.cul.feed(wrong[:15] + "654321" + wrong[21:])
        await self.settle()
        self.assertTrue(future.done())

    async def test_stats_count_attempts_and_correct_explicit_lovf(self):
        self.cul.reject = True
        task = self.send()
        await self.settle()
        self.assertEqual(self.stats("SetTemperature")["packets"], 1)
        self.assertEqual(self.stats("SetTemperature")["estimated_credits"], 0)
        self.assertEqual(self.stats("SetTemperature")["firmware_rejections"], 1)
        self.cul.reject = False
        await self.advance(5.1)
        await asyncio.wait_for(task, .5)
        stats = self.stats("SetTemperature")
        self.assertEqual(stats["packets"], 2)
        self.assertEqual(stats["estimated_credits"], 109)
        self.assertEqual(stats["retries"], 1)
        copy = self.c.get_budget_diagnostics()["traffic_by_command"]
        copy["SetTemperature"]["packets"] = 999
        self.assertEqual(self.stats("SetTemperature")["packets"], 2)

    async def test_budget_delay_counts_once_per_queue_entry(self):
        self.cul.credits = 0
        task = self.send()
        await self.settle()
        self.assertEqual(self.stats("SetTemperature")["budget_delayed"], 1)
        await self.advance(120, credits=0)
        self.assertEqual(self.stats("SetTemperature")["budget_delayed"], 1)
        self.assertEqual(self.stats("SetTemperature")["packets"], 0)
        await self.advance(120, credits=450)
        await asyncio.wait_for(task, .5)
        self.assertEqual(self.stats("SetTemperature")["estimated_credits"], 109)

    async def test_control_commands_and_replaced_debounce_intents_are_not_rf(self):
        await self.c._write_cul("Zr")
        async with self.c._cul_credit_lock:
            await self.c._query_credit()
        first = asyncio.create_task(self.c.async_set_temperature("123456", 20))
        self.tasks.append(first)
        await self.settle()
        second = asyncio.create_task(self.c.async_set_temperature("123456", 23))
        self.tasks.append(second)
        await self.settle()
        self.assertEqual((await first).status, "superseded")
        self.c.clear_queue()
        self.assertEqual((await second).status, "cancelled")
        self.assertEqual(self.c.get_budget_diagnostics()["traffic_by_command"], {})

    async def test_shutdown_cleans_shared_requests(self):
        self.cul.credits = 0
        task = self.time()
        await self.settle()
        await self.c.async_shutdown()
        self.assertEqual((await asyncio.wait_for(task, .5)).status, "cancelled")
        self.assertFalse(self.c._time_sync_requests)
        self.assertFalse(self.c._time_sync_tasks)

    async def test_known_clock_error_bypasses_automatic_cooldown(self):
        await self.time()
        self.c.get_device("123456").last_time_offset_seconds = 8
        self.assertEqual((await self.time(automatic=True)).status, "completed")
        self.assertEqual(len(self.cul.frames), 2)

    async def test_shared_time_failure_completes_all_waiters_without_leaks(self):
        self.cul.credits = 0
        first = self.time()
        second = self.time()
        await self.settle()
        self.cul.frame_hook = lambda cul, cmd: cul.feed("ZERR101")
        await self.advance(120, credits=450)
        results = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), .5)
        self.assertTrue(all(isinstance(item, ConnectionError) for item in results))
        await self.settle()
        self.assertFalse(self.c._time_sync_requests)
        self.assertFalse(self.c._time_sync_tasks)
