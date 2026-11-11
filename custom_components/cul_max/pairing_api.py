"""Admin-only live pairing results and controller-specific pairing start."""
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, area_registry as ar
from .const import DOMAIN, DEVICE_TYPE_NAMES_DE, DEFAULT_DEVICE_TYPE_NAME_DE
from .queue_api import CONTROLLERS, select_controller

DATA_KEY = f"{DOMAIN}_pairing_hub"


class PairingHub:
    def __init__(self, hass):
        self.hass = hass
        self.sessions = {}
        self.listeners = set()
        self.bindings = []
        self.timer = None
        self.registry_unsubs = [hass.bus.async_listen(event, self.changed) for event in (
            "device_registry_updated", "area_registry_updated")]
        self.registry_unsubs.append(hass.bus.async_listen_once("homeassistant_stop", self.close))

    @callback
    def rebind(self):
        for unsub in self.bindings:
            unsub()
        self.bindings.clear()
        for key, c in self.hass.data.get(CONTROLLERS, {}).items():
            c.pairing_session = self.sessions.setdefault(key, c.pairing_session)
            self.bindings.append(c.add_pairing_state_listener(self.changed))
        self.changed()

    def snapshot(self):
        registry, areas = dr.async_get(self.hass), ar.async_get(self.hass)
        controllers = []
        for key, c in self.hass.data.get(CONTROLLERS, {}).items():
            session = c.pairing_session
            devices = []
            for result in session.devices.values():
                device = c.get_device(result["address"])
                entry = registry.async_get_device(identifiers={(DOMAIN, result["address"])})
                area = areas.async_get_area(entry.area_id) if entry and entry.area_id else None
                devices.append({**result, "device_id": entry.id if entry else None, "removed": device is None and entry is None,
                    "name": (entry.name_by_user or entry.name) if entry else device.name if device else result["address"],
                    "device_type": DEVICE_TYPE_NAMES_DE.get(device.device_type, DEFAULT_DEVICE_TYPE_NAME_DE) if device else DEFAULT_DEVICE_TYPE_NAME_DE,
                    "serial_number": device.serial_number if device else None,
                    "area_name": area.name if area else None})
            rejected = []
            for result in session.rejected.values():
                device = c.get_device(result["address"])
                entry = registry.async_get_device(identifiers={(DOMAIN, result["address"])})
                rejected.append({**result, "name":
                    (entry.name_by_user or entry.name) if entry else
                    device.name if device else result["address"]})
            controllers.append({"config_entry_id": key, "name": f"MAX! CUL ({c.host}:{c.port})",
                "connected": c._writer is not None, "session_id": session.id,
                "started_at": session.started_at, "ends_at": session.ends_at,
                "active": session.active, "devices": devices, "error": session.error,
                "own_address": f"{c.own_address:06X}", "rejected": rejected})
        return {"controllers": controllers}

    @callback
    def changed(self, *_):
        if self.listeners and self.timer is None:
            self.timer = self.hass.loop.call_later(.1, self.publish)

    @callback
    def publish(self):
        self.timer = None
        data = self.snapshot()
        for listener in tuple(self.listeners):
            listener(data)

    def subscribe(self, listener):
        self.listeners.add(listener)
        listener(self.snapshot())
        def unsubscribe():
            self.listeners.discard(listener)
            if not self.listeners and self.timer:
                self.timer.cancel()
                self.timer = None
        return unsubscribe

    @callback
    def close(self, *_):
        if self.timer:
            self.timer.cancel()
        for unsub in self.bindings + self.registry_unsubs:
            unsub()
        self.bindings.clear()
        self.registry_unsubs.clear()
        self.listeners.clear()


def register_pairing_api(hass):
    import voluptuous as vol
    from homeassistant.components import websocket_api
    if DATA_KEY in hass.data:
        hass.data[DATA_KEY].rebind()
        return
    hub = hass.data[DATA_KEY] = PairingHub(hass)
    hub.rebind()

    @websocket_api.websocket_command({vol.Required("type"): "cul_max/pairing/subscribe"})
    @websocket_api.require_admin
    @websocket_api.async_response
    async def subscribe(hass, connection, msg):
        connection.send_result(msg["id"])
        connection.subscriptions[msg["id"]] = hub.subscribe(lambda data: connection.send_event(msg["id"], data))

    @websocket_api.websocket_command({vol.Required("type"): "cul_max/pairing/start",
        vol.Required("config_entry_id"): str,
        vol.Optional("duration", default=60): vol.All(int, vol.Range(min=1, max=3600))})
    @websocket_api.require_admin
    @websocket_api.async_response
    async def start(hass, connection, msg):
        try:
            c = select_controller(hass.data.get(CONTROLLERS, {}), msg["config_entry_id"])
            if c._writer is None:
                raise ValueError("CUL ist nicht verbunden")
            if c.is_pairing_mode:
                raise ValueError("Pairing ist bereits aktiv")
            await c.async_start_pairing(msg["duration"])
            connection.send_result(msg["id"], hub.snapshot())
        except ValueError as err:
            connection.send_error(msg["id"], "invalid_pairing", str(err))

    websocket_api.async_register_command(hass, subscribe)
    websocket_api.async_register_command(hass, start)
