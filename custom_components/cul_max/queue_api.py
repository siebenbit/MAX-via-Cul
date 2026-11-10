"""Public queue snapshots and Home Assistant actions, shared across controllers."""
from __future__ import annotations

from typing import Any

from .const import DOMAIN

CONTROLLERS = f"{DOMAIN}_queue_controllers"
SERVICES = ("get_queue", "delete_queue_entry", "clear_queue", "cancel_config_job")


def select_controller(controllers: dict, entry_id: str | None):
    if entry_id:
        if entry_id not in controllers:
            raise ValueError("Controller ist nicht geladen")
        return controllers[entry_id]
    if len(controllers) != 1:
        raise ValueError("Bitte einen Controller auswählen")
    return next(iter(controllers.values()))


def queue_snapshot(controllers: dict, filters: dict[str, Any]) -> dict:
    result = {"controllers": [], "entries": [], "jobs": []}
    for entry_id, coordinator in controllers.items():
        if filters.get("config_entry_id") and entry_id != filters["config_entry_id"]:
            continue
        snapshot = coordinator.get_queue()
        snapshot["config_entry_id"] = entry_id
        snapshot["name"] = f"MAX! CUL ({coordinator.host}:{coordinator.port})"
        def matches(item):
            return (not filters.get("address") or item.get("device_address") == filters["address"].upper()) and (
                not filters.get("statuses") or item.get("status") in filters["statuses"]) and (
                not filters.get("command_types") or item.get("command_type") in filters["command_types"]) and (
                not filters.get("scope") or item.get("scope") == filters["scope"])
        snapshot["entries"] = [item | {"config_entry_id": entry_id} for item in snapshot["entries"] if matches(item)]
        snapshot["jobs"] = [item | {"config_entry_id": entry_id} for item in snapshot["jobs"] if matches(item)]
        result["entries"].extend(snapshot["entries"])
        result["jobs"].extend(snapshot["jobs"])
        result["controllers"].append(snapshot)
    return result


def register_queue_services(hass) -> None:
    """Register once; resolve loaded coordinators at call time, never by closure."""
    import voluptuous as vol
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import ServiceValidationError
    from homeassistant.helpers import config_validation as cv

    if hass.services.has_service(DOMAIN, "get_queue"):
        return

    async def handle(call):
        controllers = hass.data.get(CONTROLLERS, {})
        data = call.data
        try:
            if call.service == "get_queue":
                if data.get("config_entry_id"):
                    select_controller(controllers, data["config_entry_id"])
                return queue_snapshot(controllers, data)
            if call.service == "delete_queue_entry":
                ids = data.get("entry_ids") or [data["entry_id"]]
                removed, protected = [], []
                for entry_id in ids:
                    owner = next((c for c in controllers.values() if c.has_queue_entry(entry_id)), None)
                    if owner is None:
                        if len(ids) == 1:
                            raise ValueError("Queue-Eintrag nicht mehr vorhanden")
                        protected.append({"id": entry_id, "reason": "Nicht mehr vorhanden"})
                        continue
                    try:
                        owner.delete_queue_entry(entry_id)
                        removed.append(entry_id)
                    except ValueError as err:
                        if len(ids) == 1:
                            raise
                        protected.append({"id": entry_id, "reason": str(err)})
                result = {"removed": removed, "protected": protected}
            else:
                coordinator = select_controller(controllers, data.get("config_entry_id"))
                if call.service == "clear_queue":
                    result = coordinator.clear_queue(data.get("address"))
                else:
                    result = await coordinator.async_cancel_config_job(data["job_id"], confirm=data["confirm"])
            return result if call.return_response else None
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    schemas = {
        "get_queue": vol.Schema({
            vol.Optional("config_entry_id"): cv.string, vol.Optional("address"): cv.string,
            vol.Optional("statuses"): [cv.string], vol.Optional("command_types"): [cv.string],
            vol.Optional("scope"): vol.In(["general", "configuration"]),
        }),
        "delete_queue_entry": vol.All(vol.Schema({
            vol.Exclusive("entry_id", "ids"): cv.string,
            vol.Exclusive("entry_ids", "ids"): vol.All([cv.string], vol.Length(min=1)),
        }), cv.has_at_least_one_key("entry_id", "entry_ids")),
        "clear_queue": vol.Schema({vol.Optional("config_entry_id"): cv.string, vol.Optional("address"): cv.string}),
        "cancel_config_job": vol.Schema({
            vol.Optional("config_entry_id"): cv.string, vol.Required("job_id"): cv.string,
            vol.Required("confirm"): vol.All(cv.boolean, vol.Equal(True)),
        }),
    }
    for name, schema in schemas.items():
        hass.services.async_register(DOMAIN, name, handle, schema=schema,
            supports_response=SupportsResponse.ONLY if name == "get_queue" else SupportsResponse.OPTIONAL)
