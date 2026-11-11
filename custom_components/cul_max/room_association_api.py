"""Admin-only room association endpoints using the shared live snapshot hub."""
import asyncio

from homeassistant.components import websocket_api
import voluptuous as vol

from .queue_api import CONTROLLERS
from .room_config_api import RoomConfigHub
from .room_association import DATA_KEY, RoomAssociationManager


async def register_room_association_api(hass, owner):
    lock = hass.data.setdefault(f"{DATA_KEY}_setup_lock", asyncio.Lock())
    async with lock:
        await _register_room_association_api(hass, owner)


async def _register_room_association_api(hass, owner):
    hub = hass.data.get(DATA_KEY)
    if hub:
        hub.manager.unloading.discard(owner)
        hub.rebind()
        return
    hub = RoomConfigHub(hass)
    hub.manager = RoomAssociationManager(hass, hass.data.setdefault(CONTROLLERS, {}))
    hub.manager.changed = hub.changed
    hass.data[DATA_KEY] = hub
    try:
        await hub.manager.load()
    except BaseException:
        hub.close()
        hass.data.pop(DATA_KEY, None)
        raise

    @websocket_api.websocket_command({vol.Required("type"): "cul_max/room_association/subscribe"})
    @websocket_api.require_admin
    @websocket_api.async_response
    async def subscribe(hass, connection, msg):
        connection.send_result(msg["id"])
        connection.subscriptions[msg["id"]] = hub.subscribe(lambda data: connection.send_event(msg["id"], data))

    @websocket_api.websocket_command({vol.Required("type"): "cul_max/room_association/start",
        vol.Required("config_entry_id"): str, vol.Required("area_id"): str})
    @websocket_api.require_admin
    @websocket_api.async_response
    async def start(hass, connection, msg):
        try:
            result = await hub.manager.start(msg["config_entry_id"], msg["area_id"])
        except Exception as err:
            connection.send_error(msg["id"], "association_failed", str(err))
        else:
            connection.send_result(msg["id"], result)

    websocket_api.async_register_command(hass, subscribe)
    websocket_api.async_register_command(hass, start)
