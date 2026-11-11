"""Pairing snapshots follow registry edits and retain results across reload."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import test_credit as transport


class PairingHubTests(unittest.TestCase):
    def setUp(self):
        self.registry = types.SimpleNamespace(async_get_device=lambda **kw: self.entry)
        self.entry = None
        self.area = types.SimpleNamespace(name="Bad")
        helpers = types.ModuleType("homeassistant.helpers")
        helpers.device_registry = types.SimpleNamespace(async_get=lambda hass: self.registry)
        helpers.area_registry = types.SimpleNamespace(async_get=lambda hass: types.SimpleNamespace(async_get_area=lambda key: self.area))
        core = types.ModuleType("homeassistant.core")
        core.callback = lambda f: f
        spec = importlib.util.spec_from_file_location("_cul_budget_tests.pairing_api", Path(__file__).parents[1] / "pairing_api.py")
        api = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"homeassistant":types.ModuleType("homeassistant"), "homeassistant.helpers": helpers, "homeassistant.core":core}):
            spec.loader.exec_module(api)
        self.api = api
        device = types.SimpleNamespace(name="Thermostat", device_type=1, serial_number="NEQ1234567")
        self.c = types.SimpleNamespace(pairing_session=transport.mod.PairingSession(), host="cul", port=2323, _writer=object(),
            get_device=lambda address: device, add_pairing_state_listener=lambda cb: Mock())
        self.hass = types.SimpleNamespace(data={api.CONTROLLERS:{"a":self.c}}, bus=types.SimpleNamespace(async_listen=lambda *a:Mock(), async_listen_once=lambda *a:Mock()))
        self.hub = api.PairingHub(self.hass)
        self.hub.rebind()

    def test_registry_creation_and_edits_are_resolved_live(self):
        from datetime import datetime, UTC
        self.c.pairing_session.start(datetime.now(UTC))
        self.c.pairing_session.record(self.c.pairing_session.id,"123456",False)
        row = self.hub.snapshot()["controllers"][0]["devices"][0]
        self.assertIsNone(row["device_id"])
        self.entry = types.SimpleNamespace(id="device", name="Default", name_by_user="Heizung",area_id="bad")
        row = self.hub.snapshot()["controllers"][0]["devices"][0]
        self.assertEqual((row["name"],row["area_name"],row["device_id"]),("Heizung","Bad","device"))

    def test_german_type_labels_and_unknown_fallback(self):
        from datetime import datetime, UTC
        self.c.pairing_session.start(datetime.now(UTC))
        self.c.pairing_session.record(self.c.pairing_session.id, "123456", False)
        device = self.c.get_device("123456")
        for kind, expected in {1: "Heizkörperthermostat", 2: "Heizkörperthermostat Plus",
                               3: "Wandthermostat", 4: "Fensterkontakt", 5: "Taster",
                               0: "MAX! Gerät", 255: "MAX! Gerät"}.items():
            with self.subTest(kind=kind):
                device.device_type = kind
                row = self.hub.snapshot()["controllers"][0]["devices"][0]
                self.assertEqual(row["device_type"], expected)
        self.c.get_device = lambda address: None
        self.assertEqual(self.hub.snapshot()["controllers"][0]["devices"][0]["device_type"], "MAX! Gerät")

    def test_reload_retains_results_and_controllers_stay_separate(self):
        from datetime import datetime, UTC
        self.c.pairing_session.start(datetime.now(UTC))
        self.c.pairing_session.record(self.c.pairing_session.id,"123456",False)
        self.c.pairing_session.active = False  # Coordinator shutdown ends the window.
        replacement = types.SimpleNamespace(**vars(self.c))
        replacement.pairing_session = transport.mod.PairingSession()
        self.hass.data[self.api.CONTROLLERS] = {"a":replacement,"b":self.c}
        self.hub.rebind()
        self.assertIn("123456",replacement.pairing_session.devices)
        self.assertFalse(replacement.pairing_session.active)
        self.assertEqual(len(self.hub.snapshot()["controllers"]),2)
        self.hub.close()
        self.assertFalse(self.hub.bindings)
