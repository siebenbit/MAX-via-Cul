"""Queue labels are current HA display data, never command mutations."""
import copy
import importlib
import types
import unittest
import test_credit  # Load the integration package with HA stubs.

api = importlib.import_module("_cul_budget_tests.queue_api")


class QueueNameTests(unittest.TestCase):
    def setUp(self):
        self.source = {"entries": [{"id": "entry", "device_address": "123456", "device_name": "Old entry",
            "description": "Original command", "scope": "general", "status": "queued"}],
            "jobs": [{"id": "job", "device_address": "123456", "device_name": "Old job", "scope": "configuration", "status": "queued"}]}
        self.internal = types.SimpleNamespace(name="Internal current name")
        self.c = types.SimpleNamespace(host="cul", port=2323, get_queue=lambda: copy.deepcopy(self.source), get_device=lambda address:self.internal)
        self.entry = types.SimpleNamespace(name_by_user="Heizung Bad", name="HA default")
        self.lookups = []
        def lookup(**kwargs):
            self.lookups.append(kwargs["identifiers"])
            return self.entry
        self.registry = types.SimpleNamespace(async_get_device=lookup)

    def snapshot(self):
        return api.queue_snapshot({"controller":self.c},{},registry=self.registry)

    def test_current_ha_name_applies_to_entries_jobs_and_both_snapshot_views(self):
        before = copy.deepcopy(self.source)
        for name in ("Heizung Bad", "Neuer Name <&>"):
            self.entry.name_by_user = name
            data = self.snapshot()
            for group in ("entries","jobs"):
                self.assertEqual(data[group][0]["device_name"],name)
                self.assertEqual(data["controllers"][0][group][0]["device_name"],name)
        self.assertEqual(self.source,before)
        self.assertEqual(self.lookups[0],{("cul_max","123456")})

    def test_name_fallbacks_and_addressless_protocol_entries(self):
        self.entry.name_by_user = None
        self.assertEqual(self.snapshot()["entries"][0]["device_name"],"HA default")
        self.entry = None
        self.assertEqual(self.snapshot()["entries"][0]["device_name"],"Internal current name")
        self.internal = None
        self.source["entries"][0]["device_name"] = ""
        self.assertEqual(self.snapshot()["entries"][0]["device_name"],"123456")
        self.source["entries"][0].update(device_address=None,device_name="CUL / Protokoll")
        self.assertEqual(self.snapshot()["entries"][0]["device_name"],"CUL / Protokoll")

    def test_controller_and_address_filters_stay_unchanged(self):
        data = api.queue_snapshot({"one":self.c,"two":self.c},{"config_entry_id":"two","address":"123456"},registry=self.registry)
        self.assertEqual(len(data["controllers"]),1)
        self.assertEqual(data["entries"][0]["config_entry_id"],"two")
        self.assertEqual(api.queue_snapshot({"one":self.c},{"address":"ABCDEF"},registry=self.registry)["entries"],[])
