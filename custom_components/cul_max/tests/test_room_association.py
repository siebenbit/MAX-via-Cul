"""Room mapping, retries and busy protection without Home Assistant or RF."""
import asyncio
import copy
import importlib
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

import test_room_config as configuration
import test_credit as transport

storage = types.ModuleType("homeassistant.helpers.storage")
storage.Store = lambda *args: None
with patch.dict(sys.modules, {"homeassistant.helpers.storage": storage}):
    association = importlib.import_module("_cul_budget_tests.room_association")
mod = transport.mod


class RoomAssociationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUpBase = transport.CreditTests.asyncSetUp
    settle = transport.CreditTests.settle
    attach = transport.CreditTests.attach

    async def asyncSetUp(self):
        await self.asyncSetUpBase()
        self.c.config_entry_id = "cul"
        self.c._prepare_device_for_config = AsyncMock()
        self.c._send_command = AsyncMock()
        self.c._schedule_shutter_config_processing = lambda *args, **kw: None
        self.members = []
        for address in ("123456", "234567"):
            self.c._devices[address] = mod.KnownDevice(address, 1, address, paired=True)
            self.members.append({"address": address, "config_entry_id": "cul", "area_id": "living", "area_name": "Wohnzimmer"})
        self.manager = association.RoomAssociationManager(self.c.hass, {"cul": self.c}, lambda: self.members)
        self.manager.store = types.SimpleNamespace(async_save=AsyncMock(), async_load=AsyncMock(return_value=None))
        self.c.hass.data = {association.DATA_KEY: types.SimpleNamespace(manager=self.manager)}
        helpers = types.ModuleType("homeassistant.helpers")
        helpers.device_registry = types.SimpleNamespace(async_get=lambda hass: types.SimpleNamespace(async_get_device=lambda **kw: None))
        helpers.area_registry = types.SimpleNamespace(async_get=lambda hass: types.SimpleNamespace(areas={"living": types.SimpleNamespace(id="living",name="Wohnzimmer")}))
        self.patch = patch.dict(sys.modules, {"homeassistant.helpers": helpers})
        self.patch.start()

    async def asyncTearDown(self):
        await self.manager.unload("cul")
        await transport.CreditTests.asyncTearDown(self)
        self.patch.stop()

    def room(self):
        return self.manager.snapshot()["controllers"][0]["rooms"][0]

    async def finish(self):
        await asyncio.gather(*list(self.manager.tasks.values()))

    async def test_new_mapping_saved_before_work_and_complete(self):
        await self.manager.start("cul", "living")
        self.manager.store.async_save.assert_awaited_once()
        self.assertTrue(self.room()["busy"])
        with self.assertRaises(ValueError):
            await self.manager.start("cul", "living")
        await self.finish()
        self.assertEqual(self.room()["status"], "complete")
        self.assertEqual([d.group_id for d in self.c.get_all_devices()], [1, 1])
        self.assertFalse(self.room()["can_start"])

    async def test_adopt_shared_group_and_conflicting_ids_allocate_new(self):
        self.c.get_device("123456").group_id = 5
        result = await self.manager.start("cul", "living")
        self.assertEqual(result["group_id"], 5)
        await self.finish()
        self.manager.records = {}
        self.c.get_device("234567").group_id = 7
        result = await self.manager.start("cul", "living")
        self.assertEqual(result["group_id"], 1)
        await self.finish()

    async def test_external_group_is_not_adopted_and_external_links_block(self):
        self.c._devices["345678"] = mod.KnownDevice("345678", 1, "External", paired=True, group_id=5)
        self.c.get_device("123456").group_id = 5
        self.assertEqual((await self.manager.start("cul", "living"))["group_id"], 1)
        await self.finish()
        self.c.get_device("123456").linked_partners = ["345678"]
        with self.assertRaisesRegex(ValueError, "außerhalb"):
            await self.manager.start("cul", "living")

    async def test_failure_keeps_group_and_retry_completes(self):
        self.c._send_command.side_effect = ConnectionError("offline")
        group = (await self.manager.start("cul", "living"))["group_id"]
        await self.finish()
        self.assertEqual(self.room()["status"], "partial")
        self.assertTrue(self.room()["can_start"])
        self.c._send_command.side_effect = None
        self.assertEqual((await self.manager.start("cul", "living"))["group_id"], group)
        await self.finish()
        self.assertEqual(self.room()["status"], "complete")

    async def test_sleepy_contact_blocks_across_reload_until_commands_removed(self):
        self.c.get_device("234567").device_type = mod.DEVICE_SHUTTER_CONTACT
        await self.manager.start("cul", "living")
        await self.finish()
        self.assertTrue(self.room()["busy"])
        saved = copy.deepcopy(self.manager.records)
        self.manager.records = {}
        self.manager.store.async_load.return_value = {"controllers": saved}
        await self.manager.load()
        self.assertTrue(self.room()["busy"])
        with self.assertRaises(ValueError):
            await self.c.async_set_group_id("123456", 9)
        self.c._pending_shutter_config.clear()
        self.assertFalse(self.room()["busy"])
        self.assertTrue(self.room()["can_start"])

    async def test_save_failure_sends_nothing(self):
        self.manager.store.async_save.side_effect = OSError("disk")
        with self.assertRaises(OSError):
            await self.manager.start("cul", "living")
        self.assertFalse(self.manager.records)
        self.c._send_command.assert_not_awaited()

    async def test_reserved_and_pending_groups_are_not_reallocated(self):
        self.manager.records = {"cul": {"other": {"group_id": 1, "members": []}}}
        self.c._pending_shutter_config["345678"] = [mod.PendingShutterCommand(op="set_group_id", description="", group_id=2)]
        self.assertEqual((await self.manager.start("cul", "living"))["group_id"], 3)
        await self.finish()

    async def test_unpaired_missing_cul_and_no_free_group_rejected(self):
        with self.assertRaises(ValueError):
            await self.manager.start("missing", "living")
        self.c.get_device("123456").paired = False
        with self.assertRaises(ValueError):
            await self.manager.start("cul", "living")
        self.c.get_device("123456").paired = True
        self.manager.records = {"cul": {str(g): {"group_id": g, "members": []} for g in range(1,256)}}
        with self.assertRaisesRegex(ValueError, "Keine freie"):
            await self.manager.start("cul", "living")

    async def test_unload_before_task_started_releases_runtime_lock(self):
        await self.manager.start("cul", "living")
        await self.manager.unload("cul")
        self.assertFalse(self.manager.tasks)
        self.assertFalse(self.room()["can_start"])
        self.manager.unloading.discard("cul")
        self.assertTrue(self.room()["can_start"])
        self.assertEqual(self.room()["group_id"], 1)

    async def test_membership_during_pending_work_is_frozen(self):
        self.c.get_device("234567").device_type = mod.DEVICE_SHUTTER_CONTACT
        await self.manager.start("cul", "living")
        await self.finish()
        self.members.pop()
        self.assertEqual(len(self.room()["devices"]), 2)
        self.assertTrue(self.room()["busy"])

    async def test_group_reserved_while_mapping_is_saved(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def save(data):
            entered.set()
            await release.wait()
        self.manager.store.async_save.side_effect = save
        task = asyncio.create_task(self.manager.start("cul", "living"))
        await entered.wait()
        try:
            self.assertTrue(self.room()["busy"])
            with self.assertRaisesRegex(ValueError, "läuft"):
                await self.c.async_set_group_id("123456", 9)
        finally:
            release.set()
            await task
            await self.finish()

    async def test_deferred_external_links_block_both_directions_and_both_operations(self):
        for op in ("add_link_partner", "remove_link_partner"):
            for source, target in (("345678", "123456"), ("123456", "345678")):
                with self.subTest(op=op, source=source):
                    self.c._pending_shutter_config = {source: [mod.PendingShutterCommand(
                        op=op, description="External link", partner_address=target)]}
                    room = self.room()
                    self.assertFalse(room["can_start"])
                    self.assertTrue(any("Raumgrenzen" in p for p in room["problems"]))
                    with self.assertRaisesRegex(ValueError, "Raumgrenzen"):
                        await self.manager.start("cul", "living")
        self.c._send_command.assert_not_awaited()
        self.manager.store.async_save.assert_not_awaited()

    async def test_queued_and_sent_external_links_block_both_directions(self):
        for op, build in (("AddLinkPartner", transport.protocol.build_add_link_partner),
                          ("RemoveLinkPartner", transport.protocol.build_remove_link_partner)):
            for source, target in (("345678", "123456"), ("123456", "345678")):
                for status in ("queued", "awaiting_ack"):
                    with self.subTest(op=op, source=source, status=status):
                        entry = mod.QueueEntry(source, source, op, op, asyncio.get_running_loop().create_future(),
                            payload=types.SimpleNamespace(cmd=build(1, self.c.own_address, int(source,16), int(target,16),1)), status=status)
                        self.c._command_queue.add(entry, worker=False)
                        try:
                            self.assertFalse(self.room()["can_start"])
                            with self.assertRaisesRegex(ValueError, "Raumgrenzen"):
                                await self.manager.start("cul", "living")
                        finally:
                            self.c._command_queue.finish(entry, "cancelled")
        self.c._send_command.assert_not_awaited()

    async def test_pending_links_outside_other_rooms_do_not_block(self):
        self.c._pending_shutter_config = {"345678": [mod.PendingShutterCommand(
            op="add_link_partner", description="Other room", partner_address="456789")]}
        self.assertTrue(self.room()["can_start"])
        await self.manager.start("cul", "living")
        await self.finish()
        self.assertEqual(self.room()["status"], "complete")
