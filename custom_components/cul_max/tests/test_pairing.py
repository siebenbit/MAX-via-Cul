"""Pairing session isolation and production receive/finalize behavior."""
import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
import test_credit as transport
from _cul_budget_tests.pairing import PairingSession


class PairingTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = transport.CreditTests.asyncSetUp
    asyncTearDown = transport.CreditTests.asyncTearDown
    attach = transport.CreditTests.attach
    settle = transport.CreditTests.settle
    async def test_sessions_deduplicate_and_reject_stale_results(self):
        session = PairingSession()
        session.start(datetime.now(UTC) + timedelta(seconds=60))
        old = session.id
        session.record(old, "123456", False)
        session.record(old, "123456", True)
        self.assertEqual(len(session.devices), 1)
        self.assertFalse(session.devices["123456"]["already_known"])
        session.start(datetime.now(UTC) + timedelta(seconds=60))
        session.record(old, "234567", False)
        self.assertFalse(session.devices)

    async def test_finalize_records_device_before_time_sync_failure(self):
        await self.c.async_start_pairing(60)
        self.c._ensure_time_slots_assigned = AsyncMock()
        self.c._sync_device_registry_entry = AsyncMock()
        self.c.async_send_time_information = AsyncMock(side_effect=ConnectionError("offline"))
        await self.c._finalize_pair_ping(msg=None, src="123456", device_type=1,
            firmware=1, serial_str="NEQ1234567", session_id=self.c.pairing_session.id)
        self.assertIn("123456", self.c.pairing_session.devices)
        self.assertTrue(self.c.get_device("123456").paired)

    async def test_expired_window_retains_results(self):
        await self.c.async_start_pairing(60)
        self.c.pairing_session.record(self.c.pairing_session.id, "123456", False)
        await self.c._pairing_timeout(0)
        self.assertFalse(self.c.pairing_session.active)
        self.assertIn("123456", self.c.pairing_session.devices)

    async def test_old_finalize_does_not_contaminate_new_window(self):
        await self.c.async_start_pairing(60)
        old = self.c.pairing_session.id
        await self.c.async_start_pairing(60)
        self.c._ensure_time_slots_assigned = AsyncMock()
        self.c._sync_device_registry_entry = AsyncMock()
        await self.c._finalize_pair_ping(msg=None, src="123456", device_type=4,
            firmware=1, serial_str="NEQ1234567", session_id=old)
        self.assertFalse(self.c.pairing_session.devices)

    async def test_shutdown_joins_timeout_and_stale_timeout_cannot_end_new_session(self):
        await self.c.async_start_pairing(60)
        old_id = self.c.pairing_session.id
        old_timer = self.c._pairing_task
        await self.c.async_shutdown()
        self.assertTrue(old_timer.done())
        self.assertIsNone(self.c._pairing_task)
        self.assertFalse(self.c.is_pairing_mode)
        fresh = transport.mod.CulMaxCoordinator(self.c.hass, "simulated")
        fresh.pairing_session = self.c.pairing_session
        try:
            await fresh.async_start_pairing(60)
            await self.c._pairing_timeout(0, old_id)
            await fresh._pairing_timeout(0, old_id)
            self.assertTrue(fresh.is_pairing_mode)
            self.assertTrue(fresh.pairing_session.active)
        finally:
            await fresh.async_shutdown()

    async def test_parallel_duplicate_finalize_keeps_initial_known_status(self):
        for initially_known in (False, True):
            with self.subTest(initially_known=initially_known):
                self.c._devices.clear()
                if initially_known:
                    self.c._devices["123456"] = transport.mod.KnownDevice("123456", 4, "Fenster", paired=True)
                await self.c.async_start_pairing(60)
                gate = asyncio.Event()
                calls = 0
                async def ensure():
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        await gate.wait()
                self.c._ensure_time_slots_assigned = ensure
                self.c._sync_device_registry_entry = AsyncMock()
                params = dict(msg=None, src="123456", device_type=4, firmware=1,
                    serial_str="NEQ1234567", session_id=self.c.pairing_session.id)
                first = asyncio.create_task(self.c._finalize_pair_ping(**params))
                try:
                    await self.settle()
                    await self.c._finalize_pair_ping(**params)
                finally:
                    gate.set()
                    await first
                self.assertEqual(len(self.c.pairing_session.devices), 1)
                self.assertEqual(self.c.pairing_session.devices["123456"]["already_known"], initially_known)

    async def test_repair_preserves_device_object_profile_and_settings(self):
        from dataclasses import asdict
        device = transport.mod.KnownDevice("123456", 1, "Heizung Bad", paired=True,
            serial_number="NEQ1234567", firmware_version="3", week_profile="stored-profile",
            week_profile_known_days=[0, 2], group_id=7, linked_partners=["234567"],
            comfort_temperature=23, eco_temperature=16, measurement_offset=1.5,
            time_slot=4, last_state={"mode": 1, "desired_temperature": 22},
            last_normal_target=22, acknowledged_state={"mode": 1}, pending_config=["Wochenplan"])
        self.c._devices[device.address] = device
        before = asdict(device)
        await self.c.async_start_pairing(60)
        self.c._ensure_time_slots_assigned = AsyncMock()
        self.c._sync_device_registry_entry = AsyncMock()
        self.c.async_send_time_information = AsyncMock()
        await self.c._finalize_pair_ping(msg=None, src=device.address, device_type=1,
            firmware=0, serial_str="", session_id=self.c.pairing_session.id)
        self.assertIs(self.c.get_device(device.address), device)
        after = asdict(device)
        before.pop("last_seen")
        after.pop("last_seen")
        self.assertEqual(after, before)
        self.assertTrue(device.last_seen)

    async def test_repair_reactivates_replaced_address_and_persists_configuration(self):
        import types
        mod = transport.mod
        for incoming_serial in ("NEQ1234567", ""):
            with self.subTest(incoming_serial=incoming_serial):
                a = mod.KnownDevice("123456", 1, "Heizung", paired=True,
                    serial_number="NEQ1234567", superseded_by="234567",
                    duplicate_reason="serial_number:NEQ1234567", week_profile="profile-a",
                    week_profile_known_days=[0, 3], group_id=7, linked_partners=["345678"],
                    acknowledged_state={"mode": 1})
                b = mod.KnownDevice("234567", 1, "Heizung", paired=True,
                    serial_number=a.serial_number, week_profile="profile-b")
                other = mod.KnownDevice("345678", 1, "Heizung", paired=True,
                    serial_number="OTHER12345", week_profile="profile-other")
                self.c._devices = {d.address: d for d in (a, b, other)}
                self.c._ensure_time_slots_assigned = AsyncMock()
                self.c._sync_device_registry_entry = AsyncMock()
                self.c.async_send_time_information = AsyncMock()
                await self.c.async_start_pairing(60)
                for address in (a.address, b.address, a.address):
                    await self.c._finalize_pair_ping(msg=None, src=address, device_type=1,
                        firmware=0, serial_str=incoming_serial, session_id=self.c.pairing_session.id)
                    current = self.c.get_device(address)
                    self.assertEqual(current.superseded_by, "")
                    self.assertEqual(current.duplicate_reason, "")
                    self.assertEqual([d.address for d in self.c.get_superseded_devices()],
                                     [b.address if address == a.address else a.address])
                self.assertIs(self.c.get_device(a.address), a)
                self.assertEqual((a.week_profile, a.week_profile_known_days, a.group_id,
                                  a.linked_partners, a.acknowledged_state),
                                 ("profile-a", [0, 3], 7, ["345678"], {"mode": 1}))
                self.assertEqual(b.week_profile, "profile-b")
                self.assertEqual(other.superseded_by, "")
                self.c._store = types.SimpleNamespace(async_save=AsyncMock())
                await mod.CulMaxCoordinator._save_devices(self.c)
                saved = self.c._store.async_save.call_args.args[0]["devices"]
                self.assertEqual(saved[a.address]["superseded_by"], "")
                self.assertEqual(saved[b.address]["superseded_by"], a.address)
                self.assertEqual(saved[a.address]["week_profile"], "profile-a")

    async def test_overlapping_repair_finalizers_do_not_create_replacement_cycle(self):
        mod = transport.mod
        a = mod.KnownDevice("123456", 1, "A", paired=True, serial_number="NEQ1234567",
                            superseded_by="234567", duplicate_reason="old")
        b = mod.KnownDevice("234567", 1, "B", paired=True, serial_number=a.serial_number)
        self.c._devices = {a.address: a, b.address: b}
        gate = asyncio.Event()
        entered = asyncio.Event()
        calls = 0
        async def ensure():
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await gate.wait()
        self.c._ensure_time_slots_assigned = ensure
        self.c._sync_device_registry_entry = AsyncMock()
        self.c.async_send_time_information = AsyncMock()
        await self.c.async_start_pairing(60)
        async def pair(address):
            await self.c._finalize_pair_ping(msg=None, src=address, device_type=1,
                firmware=0, serial_str=a.serial_number, session_id=self.c.pairing_session.id)
        first = asyncio.create_task(pair(a.address))
        try:
            await asyncio.wait_for(entered.wait(), .5)
            await pair(b.address)
            self.assertEqual(b.superseded_by, "")
            self.assertEqual(a.superseded_by, b.address)
        finally:
            gate.set()
            await first
        self.assertEqual(a.superseded_by, "")
        self.assertEqual(a.duplicate_reason, "")
        self.assertEqual(b.superseded_by, a.address)

    async def test_pair_ping_destination_gate_and_logging(self):
        for active in (False, True):
            for dst in (0, self.c.own_address, 0xFEDCBA):
                with self.subTest(active=active, dst=dst):
                    self.c._pairing_mode = active
                    self.c.pairing_session.start(datetime.now(UTC) + timedelta(seconds=60))
                    self.c.pairing_session.active = active
                    self.c._handle_pair_ping = AsyncMock()
                    self.c._schedule_rx_response = lambda coro: asyncio.create_task(coro)
                    line = f"Z0B010000ABCDEF{dst:06X}0004"
                    with self.assertLogs(transport.mod.__name__, level="INFO") as logs:
                        await self.c._handle_line(line)
                    await self.settle()
                    self.assertIn(f"partner_address={dst:06X}", logs.output[0])
                    self.assertEqual(self.c._handle_pair_ping.await_count,
                                     int(active and dst != 0xFEDCBA))
                    self.assertEqual(bool(self.c.pairing_session.rejected),
                                     active and dst == 0xFEDCBA)
                    self.assertIsNone(self.c.get_device("ABCDEF"))

    async def test_foreign_pair_ping_cannot_send_or_change_existing_device(self):
        await self.c.async_start_pairing(60)
        device = transport.mod.KnownDevice("ABCDEF", 1, "Heizung", paired=False)
        self.c._devices[device.address] = device
        self.c._send_raw = AsyncMock()
        self.c._finalize_pair_ping = AsyncMock()
        msg = transport.protocol.parse_message("Z0B010000ABCDEFFEDCBA0004")
        await self.c._process_pair_ping(msg, self.c.pairing_session.id)
        self.c._send_raw.assert_not_awaited()
        self.c._finalize_pair_ping.assert_not_awaited()
        self.assertFalse(device.paired)

    async def test_rejections_follow_session_lifecycle(self):
        session = PairingSession()
        session.start(datetime.now(UTC))
        old = session.id
        session.reject(old, "ABCDEF", "111111")
        session.reject(old, "ABCDEF", "222222")
        self.assertEqual(len(session.rejected), 1)
        self.assertEqual(session.rejected["ABCDEF"]["partner_address"], "222222")
        session.active = False
        session.reject(old, "ABCDEF", "333333")
        self.assertEqual(session.rejected["ABCDEF"]["partner_address"], "222222")
        session.record(old, "ABCDEF", False)
        self.assertFalse(session.rejected)
        session.start(datetime.now(UTC))
        session.reject(old, "ABCDEF", "111111")
        self.assertFalse(session.rejected)
