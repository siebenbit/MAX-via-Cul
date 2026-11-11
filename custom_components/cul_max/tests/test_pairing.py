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
