"""Admin-only room actions and coalesced live snapshots over HA's WebSocket API."""
from __future__ import annotations

from homeassistant.core import callback

from .const import DOMAIN
from .queue_api import CONTROLLERS
from .room_config import RoomConfigManager, fingerprint

DATA_KEY = f"{DOMAIN}_room_configuration"
SERVICES = ("get_room_config", "save_room_config", "discard_room_config")


class RoomConfigHub:
    def __init__(self, hass):
        self.hass = hass
        self.manager = RoomConfigManager(hass, hass.data.setdefault(CONTROLLERS, {}))
        self.listeners = set()
        self.bindings = []
        self.timer = None
        self.last_snapshot = None
        self.registry_unsubs = [hass.bus.async_listen(name, self.changed) for name in (
            "area_registry_updated", "device_registry_updated", "entity_registry_updated")]
        self.registry_unsubs.append(hass.bus.async_listen_once("homeassistant_stop", self.stopped))
        self.rebind()

    @callback
    def rebind(self, *, notify=True):
        for unsubscribe in self.bindings:
            unsubscribe()
        self.bindings.clear()
        for c in self.manager.controllers.values():
            self.bindings.append(c.add_queue_listener(self.changed))
            self.bindings.append(c.add_global_listener(self.changed))
            for device in c.get_all_devices():
                self.bindings.append(c.add_diagnostic_listener(device.address, self.changed))
                self.bindings.append(c.add_week_profile_listener(device.address, self.changed))
        self.bound_devices = {(id(c), d.address) for c in self.manager.controllers.values() for d in c.get_all_devices()}
        if notify:
            self.changed()

    @callback
    def changed(self, *_):
        if self.listeners and self.timer is None:
            self.timer = self.hass.loop.call_later(.1, self.publish)

    @callback
    def publish(self):
        self.timer = None
        if self.bound_devices != {(id(c), d.address) for c in self.manager.controllers.values() for d in c.get_all_devices()}:
            self.rebind(notify=False)
        data = self.manager.snapshot()
        digest = fingerprint(data)
        if digest != self.last_snapshot:
            self.last_snapshot = digest
            for listener in tuple(self.listeners):
                listener(data)

    def subscribe(self, listener):
        self.listeners.add(listener)
        listener(self.manager.snapshot())
        def unsubscribe():
            self.listeners.discard(listener)
            if not self.listeners and self.timer is not None:
                self.timer.cancel()
                self.timer = None
        return unsubscribe

    @callback
    def stopped(self, _):
        self.close()

    @callback
    def close(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        for unsubscribe in self.bindings + self.registry_unsubs:
            unsubscribe()
        self.bindings.clear()
        self.registry_unsubs.clear()
        self.listeners.clear()


def register_room_config_api(hass):
    import voluptuous as vol
    from homeassistant.components import websocket_api
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import ServiceValidationError
    from homeassistant.helpers import config_validation as cv
    from homeassistant.helpers.service import async_register_admin_service

    hub = hass.data.get(DATA_KEY)
    if hub is None:
        hub = hass.data[DATA_KEY] = RoomConfigHub(hass)

        @websocket_api.websocket_command({vol.Required("type"): "cul_max/room_config/subscribe"})
        @websocket_api.require_admin
        @websocket_api.async_response
        async def subscribe(hass, connection, msg):
            connection.send_result(msg["id"])
            connection.subscriptions[msg["id"]] = hub.subscribe(
                lambda data: connection.send_event(msg["id"], data))

        websocket_api.async_register_command(hass, subscribe)
    else:
        hub.rebind()

    async def handle(call):
        try:
            if call.service == "get_room_config":
                return hub.manager.snapshot()
            result = (await hub.manager.discard(**call.data) if call.service == "discard_room_config"
                      else await hub.manager.save(**call.data))
            hub.changed()
            return result
        except (ValueError, TypeError) as err:
            raise ServiceValidationError(str(err)) from err

    schemas = {
        "get_room_config": vol.Schema({}),
        "discard_room_config": vol.Schema({vol.Required("area_id"): cv.string, vol.Required("expected_revision"): dict}),
        "save_room_config": vol.Schema({
            vol.Required("area_id"): cv.string, vol.Required("changes"): dict,
            vol.Required("expected_revision"): dict, vol.Required("operation_id"): cv.string,
        }),
    }
    for name, schema in schemas.items():
        if not hass.services.has_service(DOMAIN, name):
            async_register_admin_service(hass, DOMAIN, name, handle, schema, SupportsResponse.ONLY)
