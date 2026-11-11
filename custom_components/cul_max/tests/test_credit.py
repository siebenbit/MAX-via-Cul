"""Exercise the real coordinator and single reader with a simulated CUL."""
from __future__ import annotations

import asyncio
from datetime import datetime
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

BASE = Path(__file__).parents[1]


def load_coordinator():
    """Stub HA imports only; execute the complete integration modules."""
    prefix = "_cul_budget_tests"
    package = types.ModuleType(prefix)
    package.__path__ = [str(BASE)]
    sys.modules[prefix] = package
    names = ["homeassistant", "homeassistant.const", "homeassistant.core",
             "homeassistant.helpers", "homeassistant.helpers.storage",
             "homeassistant.helpers.device_registry", "homeassistant.util",
             "homeassistant.util.dt"]
    stubs = {name: types.ModuleType(name) for name in names}
    stubs["homeassistant.const"].Platform = types.SimpleNamespace(
        **{name: name.lower() for name in ("BUTTON", "CLIMATE", "BINARY_SENSOR", "NUMBER", "SENSOR", "TEXT")})
    stubs["homeassistant.core"].HomeAssistant = object
    stubs["homeassistant.core"].callback = lambda f: f
    stubs["homeassistant.helpers.storage"].Store = lambda *args: object()
    stubs["homeassistant.util.dt"].now = lambda: datetime.now().astimezone()
    loaded = {}
    with patch.dict(sys.modules, stubs):
        for name in ("const", "protocol", "coordinator"):
            spec = importlib.util.spec_from_file_location(f"{prefix}.{name}", BASE / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            loaded[spec.name] = module
    sys.modules.update(loaded)
    return module, loaded[f"{prefix}.protocol"]


mod, protocol = load_coordinator()


class Clock:
    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.offset = 0.0

    def time(self):
        return self.loop.time() + self.offset

    def __getattr__(self, name):
        return getattr(self.loop, name)


class SimulatedCUL:
    """A serial firmware command processor; no sockets or radio hardware."""
    def __init__(self, coordinator, credits=450):
        self.coordinator = coordinator
        self.reader = asyncio.StreamReader()
        self.credits = credits
        self.commands = []
        self.frames = []
        self.closed = False
        self.reject = False
        self.reply = True
        self.query_hook = None
        self.frame_hook = None

    def feed(self, line):
        self.reader.feed_data((line + "\r\n").encode("ascii"))

    def write(self, data):
        command = data.decode("ascii").strip()
        self.commands.append(command)
        if command == "X":
            if self.query_hook:
                self.query_hook(self)
            if self.reply:
                self.feed(f"00{self.credits:5d}")
        elif command.startswith(("Zs", "Zf")):
            cost = self.coordinator._estimate_cul_credit_cost(command)
            if self.reject or cost > self.credits:
                self.feed("LOVF")
            else:
                self.credits -= int(cost)
                self.frames.append(command)
                if self.frame_hook:
                    self.frame_hook(self, command)

    async def drain(self):
        await asyncio.sleep(0)

    def close(self):
        if not self.closed:
            self.closed = True
            self.reader.feed_eof()

    async def wait_closed(self):
        pass


def ack_line(command, *, counter=None, src=None):
    packet = bytes.fromhex(command.strip()[2:])
    return (f"Z0B{packet[1] if counter is None else counter:02X}0002"
            f"{int.from_bytes(packet[7:10], 'big') if src is None else src:06X}"
            f"{int.from_bytes(packet[4:7], 'big'):06X}0000")


class CreditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = Clock()
        self.c = mod.CulMaxCoordinator(types.SimpleNamespace(loop=self.clock), "simulated")
        self.c._schedule_reconnect = lambda: None
        for name in ("_touch_device", "_update_device_state", "_update_device_group", "_save_devices"):
            setattr(self.c, name, AsyncMock())
        self.c._dispatch = lambda msg, decoded: self.received.append(msg)
        self.received = []
        self.tasks = []
        self.attach()
        self.cmd = protocol.build_set_temperature(7, self.c.own_address, 0x123456, 20)

    def attach(self, credits=450):
        self.cul = SimulatedCUL(self.c, credits)
        self.c._reader = self.cul.reader
        self.c._writer = self.cul
        self.c._connection_ready.set()
        self.c._read_task = asyncio.create_task(self.c._read_loop())
        self.tasks.append(self.c._read_task)

    def send(self, command=None, **kwargs):
        task = asyncio.create_task(self.c._send_raw(command or self.cmd, **kwargs))
        self.tasks.append(task)
        return task

    async def settle(self):
        for _ in range(25):
            await asyncio.sleep(0)

    async def advance(self, seconds, credits=None):
        self.clock.offset += seconds
        if credits is not None:
            self.cul.credits = credits
        self.c._radio_changed.set()
        await self.settle()

    async def asyncTearDown(self):
        await self.c.async_shutdown()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def test_sufficient_credits_immediately_send(self):
        await asyncio.wait_for(self.send(), .5)
        self.assertEqual(self.cul.frames, [self.cmd.strip()])
        self.assertEqual(self.cul.commands, ["X", self.cmd.strip(), "X"])

    async def test_cost_matches_firmware_for_both_preambles(self):
        for length in range(11, 60):
            packet = bytes([length - 1]) + bytes(length - 1)
            for prefix, overhead in (("Zs", 100), ("Zf", 0)):
                self.assertEqual(self.c._estimate_cul_credit_cost(prefix + packet.hex()), overhead + length * 8 // 10)
        self.assertEqual(self.c._estimate_cul_credit_cost("X"), 0)
        with self.assertRaises(ValueError):
            self.c._estimate_cul_credit_cost("Zs0B00")

    async def test_low_budget_waits_and_requeries(self):
        self.cul.credits = 1
        task = self.send()
        await self.settle()
        self.assertEqual(self.cul.commands, ["X"])
        self.assertFalse(task.done())
        wait = self.c.get_budget_diagnostics()["retry_in_seconds"]
        self.assertGreater(wait, 100)
        await self.advance(wait, credits=450)
        await asyncio.wait_for(task, .5)
        self.assertEqual(len(self.cul.frames), 1)

    async def test_multiple_requests_do_not_share_credits(self):
        cost = int(self.c._estimate_cul_credit_cost(self.cmd))
        self.cul.credits = cost + 1
        first, second = self.send(), self.send()
        await self.settle()
        self.assertTrue(first.done())
        self.assertFalse(second.done())
        self.assertEqual(len(self.cul.frames), 1)
        await self.advance(200, credits=cost + 1)
        await asyncio.wait_for(second, .5)
        self.assertEqual(len(self.cul.frames), 2)

    async def test_priority_precedes_waiting_normal_without_bypassing_budget(self):
        self.cul.credits = 0
        normal = self.send()
        await self.settle()
        urgent_cmd = protocol.build_pair_pong(8, self.c.own_address, 0x234567)
        urgent = self.send(urgent_cmd, priority=True)
        await self.settle()
        self.assertFalse(urgent.done())
        self.assertEqual(self.cul.frames, [])
        await self.advance(300, credits=450)
        await asyncio.wait_for(asyncio.gather(normal, urgent), .5)
        self.assertEqual(self.cul.frames[0], urgent_cmd.strip())

    async def test_reconnect_synchronizes_actual_low_budget(self):
        await self.c._close_connection()
        fresh = SimulatedCUL(self.c, 2)
        with patch.object(mod.asyncio, "open_connection", AsyncMock(return_value=(fresh.reader, fresh))):
            self.assertTrue(await self.c._connect())
        self.tasks.append(self.c._read_task)
        self.cul = fresh
        self.assertEqual(self.c.get_budget_diagnostics()["reported_credits"], 2)
        self.assertEqual(fresh.commands, ["Zr", "X"])
        task = self.send()
        await self.settle()
        self.assertFalse(task.done())
        self.assertEqual(fresh.frames, [])

    async def test_query_timeout_pauses_and_late_response_cannot_grant_credit(self):
        self.cul.reply = False
        task = self.send()
        with patch.object(mod, "CUL_CREDIT_QUERY_TIMEOUT", .01):
            await asyncio.sleep(.03)
        self.assertFalse(task.done())
        self.assertTrue(self.cul.closed)
        self.assertFalse(self.c._credit_valid)
        self.assertEqual(self.cul.frames, [])
        await self.c._handle_line("00  900")
        self.assertFalse(self.c._credit_valid)
        self.attach(450)
        await self.advance(10)
        await asyncio.wait_for(task, .5)

    async def test_invalid_answers_do_not_resolve_query(self):
        self.cul.reply = False
        async with self.c._cul_credit_lock:
            query = asyncio.create_task(self.c._query_credit())
            await self.settle()
            for line in ("00  901", "00   -1", "00 4.5", "garbage", "X", "00000000"):
                self.cul.feed(line)
            await self.settle()
            self.assertFalse(query.done())
            self.cul.feed("AB    0")
            self.assertEqual(await query, 0)

    async def test_max_and_acks_are_read_during_credit_query(self):
        cmd = self.cmd
        future = self.clock.create_future()
        self.c._pending_ack = mod.PendingAck(7, "123456", future, "test")
        def incoming(cul):
            cul.feed(ack_line(cmd, counter=8))
            cul.feed(ack_line(cmd, src=0x654321))
            cul.feed(ack_line(cmd))
            cul.feed("Z0B0904301234560000000012")
        self.cul.query_hook = incoming
        async with self.c._cul_credit_lock:
            self.assertEqual(await self.c._query_credit(), 450)
        self.assertEqual(future.result().counter, 7)
        self.assertTrue(any(msg.msg_type == 0x30 for msg in self.received))

    async def test_disconnect_during_query_keeps_request(self):
        self.cul.reply = False
        task = self.send()
        await self.settle()
        self.cul.close()
        await self.settle()
        self.assertFalse(task.done())
        self.assertFalse(self.c._credit_valid)
        self.assertEqual(self.cul.frames, [])

    async def test_repeated_lovf_uses_increasing_backoff(self):
        self.cul.reject = True
        task = self.send()
        await self.settle()
        self.assertFalse(task.done())
        first_delay = self.c.get_budget_diagnostics()["retry_in_seconds"]
        count = len(self.cul.commands)
        self.c._radio_changed.set()
        await self.settle()
        self.assertEqual(len(self.cul.commands), count)
        await self.advance(5.1)
        second_delay = self.c.get_budget_diagnostics()["retry_in_seconds"]
        self.assertGreater(second_delay, first_delay)
        self.cul.reject = False
        await self.advance(10.1)
        await asyncio.wait_for(task, .5)

    async def test_week_profile_ack_retry_and_sequential_delivery(self):
        self.c._command_worker_task = asyncio.create_task(self.c._command_worker())
        counts = {}
        def reply(cul, command):
            counter = bytes.fromhex(command[2:])[1]
            counts[counter] = counts.get(counter, 0) + 1
            if counter != 20 or counts[counter] > 1:
                cul.feed(ack_line(command))
        self.cul.frame_hook = reply
        commands = [protocol.build_config_week_profile(counter, self.c.own_address, 0x123456, 2, part, "28" * (14 if part == 0 else 12))
                    for counter, part in ((20, 0), (21, 1))]
        tasks = [asyncio.create_task(self.c._send_command(cmd, expected_src="123456", device_address=None,
                 counter=counter, description="week profile", timeout=.01, retries=2))
                 for cmd, counter in zip(commands, (20, 21))]
        self.tasks.extend(tasks)
        await asyncio.wait_for(asyncio.gather(*tasks), .5)
        self.assertEqual(self.cul.frames, [commands[0].strip(), commands[0].strip(), commands[1].strip()])
        self.assertEqual(counts, {20: 2, 21: 1})

    async def test_no_idle_budget_polling(self):
        await self.send()
        commands = list(self.cul.commands)
        await asyncio.sleep(.01)
        self.assertEqual(self.cul.commands, commands)

    async def test_pairing_reply_does_not_block_reader(self):
        self.c._pairing_mode = True
        self.c._finalize_pair_ping = AsyncMock()
        self.cul.credits = 0
        self.cul.feed(f"Z0B010000123456{self.c.own_address:06X}0004")
        await self.settle()
        self.assertTrue(self.c._rx_response_tasks)
        # The PairPong is waiting, but X and other MAX frames still get read.
        self.cul.feed("Z0B0904302345670000000012")
        await self.settle()
        self.assertTrue(any(msg.src_hex == "234567" for msg in self.received))
        await self.advance(300, credits=450)
        await self.settle()
        self.assertEqual(len(self.cul.frames), 1)
        self.assertEqual(bytes.fromhex(self.cul.frames[0][2:])[3], 1)
        self.c._finalize_pair_ping.assert_awaited_once()

    async def test_ack_is_armed_only_when_packet_is_written(self):
        self.cul.credits = 0
        task = asyncio.create_task(self.c._send_command(
            self.cmd, expected_src="123456", device_address=None, counter=7,
            description="temperature", timeout=.01, retries=0))
        self.tasks.append(task)
        self.c._command_worker_task = asyncio.create_task(self.c._command_worker())
        await self.settle()
        self.assertIsNone(self.c._pending_ack)
        self.cul.feed(ack_line(self.cmd))
        await self.settle()
        self.assertFalse(task.done())
        self.cul.frame_hook = lambda cul, cmd: cul.feed(ack_line(cmd))
        await self.advance(300, credits=450)
        await asyncio.wait_for(task, .5)
        self.assertEqual(len(self.cul.frames), 1)

    async def test_ack_proves_delivery_when_post_query_times_out(self):
        self.cul.frame_hook = lambda cul, cmd: (cul.feed(ack_line(cmd)), setattr(cul, "reply", False))
        self.c._command_worker_task = asyncio.create_task(self.c._command_worker())
        with patch.object(mod, "CUL_CREDIT_QUERY_TIMEOUT", .01):
            result = await asyncio.wait_for(self.c._send_command(
                self.cmd, expected_src="123456", device_address=None, counter=7,
                description="temperature", timeout=.1, retries=2), .5)
        self.assertEqual(result.counter, 7)
        self.assertEqual(len(self.cul.frames), 1)
        self.assertFalse(self.c._credit_valid)

    async def test_firmware_error_fails_the_correct_raw_request(self):
        self.cul.frame_hook = lambda cul, cmd: cul.feed("ZERR101")
        with self.assertRaisesRegex(ConnectionError, "ZERR101"):
            await asyncio.wait_for(self.send(), .5)
        self.assertEqual(len(self.cul.frames), 1)

    async def test_write_failure_invalidates_connection(self):
        self.cul.write = lambda data: (_ for _ in ()).throw(BrokenPipeError("broken"))
        task = self.send()
        await self.settle()
        self.assertFalse(task.done())
        self.assertTrue(self.cul.closed)
        self.assertFalse(self.c._credit_valid)

    async def test_diagnostics_retain_last_measurement_as_invalid(self):
        async with self.c._cul_credit_lock:
            await self.c._query_credit()
        await self.c._close_connection()
        data = self.c.get_budget_diagnostics()
        self.assertEqual(data["reported_credits"], 450)
        self.assertFalse(data["budget_valid"])
        self.assertIsNotNone(data["last_budget_query_at"])

    async def test_late_ack_during_barrier_does_not_extend_deadline(self):
        def delayed_ack(cul):
            if cul.frames:
                self.clock.offset += 1
                cul.feed(ack_line(self.cmd))
        self.cul.query_hook = delayed_ack
        self.c._command_worker_task = asyncio.create_task(self.c._command_worker())
        results = await asyncio.wait_for(asyncio.gather(self.c._send_command(
            self.cmd, expected_src="123456", device_address=None, counter=7,
            description="temperature", timeout=.1, retries=0), return_exceptions=True), .5)
        self.assertIsInstance(results[0], ConnectionError)
        self.assertIn("No ACK", str(results[0]))
        self.assertEqual(len(self.cul.frames), 1)

    async def test_lovf_backoff_is_capped(self):
        self.cul.reject = True
        task = self.send()
        await self.settle()
        for expected in (5, 10, 20, 40, 60, 60):
            self.assertAlmostEqual(self.c.get_budget_diagnostics()["retry_in_seconds"], expected, delta=.1)
            self.assertFalse(task.done())
            await self.advance(expected + .1)
        self.assertEqual(self.cul.frames, [])

    async def test_priority_lovf_does_not_consume_another_commands_ack(self):
        first_written = asyncio.Event()
        self.cul.frame_hook = lambda cul, cmd: first_written.set()
        self.c._command_worker_task = asyncio.create_task(self.c._command_worker())
        normal = asyncio.create_task(self.c._send_command(
            self.cmd, expected_src="123456", device_address=None, counter=7,
            description="temperature", timeout=.5, retries=0))
        self.tasks.append(normal)
        await asyncio.wait_for(first_written.wait(), .5)
        await self.settle()
        self.cul.reject = True
        urgent = self.send(protocol.build_pair_pong(8, self.c.own_address, 0x234567), priority=True)
        await self.settle()
        self.assertFalse(urgent.done())
        self.cul.feed(ack_line(self.cmd))
        result = await asyncio.wait_for(normal, .5)
        self.assertEqual(result.counter, 7)
        self.assertFalse(urgent.done())

    async def test_unknown_budget_shutdown_cancels_waiting_requests(self):
        self.cul.credits = 0
        task = self.send()
        await self.settle()
        await self.c.async_shutdown()
        await self.settle()
        self.assertTrue(task.cancelled())
        self.assertFalse(self.c._rx_response_tasks)
        self.assertFalse(self.c._radio_requests)

    async def test_connect_query_write_failure_does_not_crash_reader(self):
        await self.c._close_connection()
        fresh = SimulatedCUL(self.c, 2)
        write = fresh.write
        def fail_query(data):
            if data.strip() == b"X":
                raise BrokenPipeError("query write failed")
            write(data)
        fresh.write = fail_query
        with patch.object(mod.asyncio, "open_connection", AsyncMock(return_value=(fresh.reader, fresh))):
            self.assertTrue(await self.c._connect())
        self.tasks.append(self.c._read_task)
        await self.settle()
        self.assertFalse(self.c._credit_valid)
        self.assertTrue(fresh.closed)
        self.assertIsNone(self.c._read_task.exception())
