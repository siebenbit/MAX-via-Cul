"""Idle TCP probes use the real single reader and simulated CUL, without RF."""
import asyncio
import unittest
from unittest.mock import Mock, patch
import test_credit as transport

mod = transport.mod


class HeartbeatTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = transport.CreditTests.asyncSetUp
    asyncTearDown = transport.CreditTests.asyncTearDown
    attach = transport.CreditTests.attach
    settle = transport.CreditTests.settle
    advance = transport.CreditTests.advance

    async def test_idle_probe_accepts_zero_and_rx_postpones_next_probe(self):
        await self.c._check_heartbeat()
        self.assertEqual(self.cul.commands, [])
        await self.advance(60, credits=0)
        await self.c._check_heartbeat()
        self.assertEqual(self.cul.commands, ["X"])
        self.assertTrue(self.c._credit_valid)
        await self.c._check_heartbeat()
        self.assertEqual(self.cul.commands, ["X"])
        await self.advance(59)
        self.cul.feed("Z0B90053004D7D20491F3001232")
        await self.settle()
        await self.advance(2)
        await self.c._check_heartbeat()
        self.assertEqual(self.cul.commands, ["X"])
        self.assertEqual(len(self.received), 1)
        self.assertFalse(self.cul.frames)

    async def test_credit_lock_rechecks_rx_and_prevents_duplicate_queries(self):
        await self.advance(60)
        async with self.c._cul_credit_lock:
            tasks = [asyncio.create_task(self.c._check_heartbeat()) for _ in range(2)]
            await self.settle()
            self.assertEqual(self.cul.commands, [])
        await asyncio.gather(*tasks)
        self.assertEqual(self.cul.commands, ["X"])

    async def test_timeout_reconnects_once_and_late_answer_cannot_grant_credits(self):
        await self.advance(60)
        self.cul.reply = False
        self.c._schedule_reconnect = Mock()
        with patch.object(mod, "CUL_CREDIT_QUERY_TIMEOUT", .01):
            await self.c._check_heartbeat()
        self.assertTrue(self.cul.closed)
        self.c._schedule_reconnect.assert_called_once()
        self.assertFalse(self.c._credit_valid)
        await self.c._handle_line("00  900")
        self.assertFalse(self.c._credit_valid)
        self.assertFalse(self.cul.frames)

    async def test_old_query_failure_does_not_close_replacement_connection(self):
        await self.advance(60)
        self.cul.reply = False
        task = asyncio.create_task(self.c._check_heartbeat())
        await self.settle()
        await self.c._close_connection()
        self.attach()
        await task
        self.assertFalse(self.cul.closed)
        self.assertIs(self.c._writer, self.cul)

    async def test_query_waiting_for_write_lock_cannot_probe_new_connection(self):
        await self.advance(60)
        async with self.c._send_lock:
            task = asyncio.create_task(self.c._check_heartbeat())
            await self.settle()
            await self.c._close_connection()
            self.attach()
        await task
        self.assertFalse(self.cul.closed)
        self.assertEqual(self.cul.commands, [])

    async def test_received_frames_are_dispatched_during_probe(self):
        await self.advance(60)
        self.cul.query_hook = lambda cul: cul.feed("Z0B90053004D7D20491F3001232")
        await self.c._check_heartbeat()
        await self.settle()
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.cul.commands, ["X"])

    async def test_shutdown_cancels_probe_and_never_reconnects(self):
        await self.advance(60)
        self.cul.reply = False
        self.c._schedule_reconnect = Mock()
        self.c._heartbeat_task = asyncio.create_task(self.c._check_heartbeat())
        await self.settle()
        await self.c.async_shutdown()
        self.assertIsNone(self.c._heartbeat_task)
        self.assertIsNone(self.c._credit_response)
        self.c._schedule_reconnect.assert_not_called()
