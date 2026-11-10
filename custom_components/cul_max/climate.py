"""Climate entities for MAX! thermostats (HeatingThermostat + WallMountedThermostat)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from . import CulMaxConfigEntry
from .const import (
    DOMAIN,
    MODE_AUTO,
    MODE_BOOST,
    MODE_MANUAL,
    MODE_VACATION,
    MODE_NAMES,
    TEMP_MAX,
    TEMP_MIN,
    CLIMATE_DEVICE_TYPES,
)
from .coordinator import CulMaxCoordinator, KnownDevice
from .protocol import (
    MaxMessage,
    format_week_profile_by_day,
    format_week_profile_lines,
)

# HA 2026.11 introduced native temperature properties. Keep older supported HA
# versions working without defining deprecated members on current HA.
_NATIVE_TEMPERATURE_API = hasattr(ClimateEntity, "native_temperature_unit")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CulMaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up climate entities for all known thermostat devices."""
    coordinator: CulMaxCoordinator = entry.runtime_data
    entities = []
    known_addresses: set[str] = set()

    for device in coordinator.get_all_devices():
        if device.device_type in CLIMATE_DEVICE_TYPES:
            entities.append(CulMaxClimate(coordinator, device))
            known_addresses.add(device.address)

    # Also handle dynamically paired devices
    @callback
    def on_new_device(msg: MaxMessage, decoded: Any) -> None:
        device = None
        if isinstance(decoded, KnownDevice):
            device = decoded
        else:
            device = coordinator.get_device(msg.src_hex)

        if (
            device
            and device.device_type in CLIMATE_DEVICE_TYPES
            and device.address not in known_addresses
        ):
            known_addresses.add(device.address)
            async_add_entities([CulMaxClimate(coordinator, device)])

    entry.async_on_unload(coordinator.add_global_listener(on_new_device))

    async_add_entities(entities)


class CulMaxClimate(ClimateEntity):
    """Climate entity for a MAX! HeatingThermostat or WallMountedThermostat."""

    _attr_has_entity_name = False
    _attr_name = None
    _attr_translation_key = "thermostat"
    if _NATIVE_TEMPERATURE_API:
        _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    else:
        _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = TEMP_MIN
    _attr_max_temp = TEMP_MAX
    _attr_target_temperature_step = 0.5
    _attr_hvac_modes = [HVACMode.AUTO, HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
    )
    _attr_preset_modes = ["none", "boost"]

    def __init__(self, coordinator: CulMaxCoordinator, device: KnownDevice) -> None:
        self._coordinator = coordinator
        self._device = device
        self._address = device.address

        self._attr_unique_id = f"{DOMAIN}_{self._address}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._address)},
            name=device.name,
            manufacturer="eQ-3",
            model=coordinator.get_device_registry_model(device),
        )

        self._apply_display_state()

    def _raw_mode(self) -> int | None:
        return self._coordinator.get_display_state(self._address)["mode"]

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.add_week_profile_listener(self._address, self._on_week_profile_update)
        )
        self.async_on_remove(
            self._coordinator.add_temperature_listener(self._address, self._on_temperature_intent)
        )
        self._apply_display_state()

    @callback
    def _on_temperature_intent(self) -> None:
        # Also called for unsolicited and partial reports, without queue activity.
        self._apply_display_state()
        self.async_write_ha_state()

    @callback
    def _on_week_profile_update(self) -> None:
        self.async_write_ha_state()

    def _apply_display_state(self) -> None:
        state = self._coordinator.get_display_state(self._address)
        self._attr_hvac_mode = HVACMode(state["hvac_mode"]) if state["hvac_mode"] else None
        self._attr_preset_mode = state["preset_mode"]
        self._attr_hvac_action = None
        if _NATIVE_TEMPERATURE_API:
            self._attr_native_target_temperature = state["target_temperature"]
            self._attr_native_current_temperature = state["current_temperature"]
        else:
            self._attr_target_temperature = state["target_temperature"]
            self._attr_current_temperature = state["current_temperature"]
        self._attr_available = any(state[key] is not None for key in
                                   ("mode", "target_temperature", "current_temperature"))
        self._attr_preset_modes = ["none", "boost"]
        until = state["until"]
        if state["preset_mode"] == "away" or (until and until.timestamp() > datetime.now().timestamp()):
            self._attr_preset_modes.append("away")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        effective_week_profile = self._coordinator.get_effective_week_profile(self._address)
        attrs: dict[str, Any] = {
            "address": self._address,
            "serial_number": self._device.serial_number or None,
            "firmware_version": self._device.firmware_version or None,
            "is_paired": self._coordinator.is_device_paired(self._address),
            "pairing_state": self._coordinator.get_pairing_state(self._address),
            "device_label": (
                f"{self._device.serial_number} / {self._address}"
                if self._device.serial_number
                else self._address
            ),
            "is_virtual": self._device.is_virtual,
            "superseded_by": self._device.superseded_by or None,
            "duplicate_reason": self._device.duplicate_reason or None,
            "pending_config": self._device.pending_config,
            "config_pending": bool(self._device.pending_config),
            "last_command": self._device.last_command or None,
            "mode_detail": MODE_NAMES.get(self._raw_mode(), self._raw_mode()),
            "mode_is_temporary": self._raw_mode() == MODE_VACATION,
            "expected_week_profile_temperature": self._coordinator.get_expected_week_profile_temperature(self._address),
            "group_id": self._device.group_id,
            "linked_partners": self._device.linked_partners,
            "comfort_temperature": self._device.comfort_temperature,
            "eco_temperature": self._device.eco_temperature,
            "window_open_temperature": self._device.window_open_temperature,
            "window_open_duration_min": self._device.window_open_duration,
            "measurement_offset": self._device.measurement_offset,
            "peer_names": self._coordinator.get_peer_names(self._address),
            "peer_labels": self._coordinator.get_peer_labels(self._address),
            "supported_partner_types": self._coordinator.get_supported_partner_type_names(self._device.device_type),
        }
        validation = self._coordinator.get_week_profile_validation(self._address)
        attrs["week_profile_validation"] = validation.get("state")
        attrs["week_profile_validation_reason"] = validation.get("reason")
        attrs["window_open_active"] = validation.get("window_open_active")
        attrs["open_window_partners"] = validation.get("open_window_partners")
        attrs["open_window_partner_names"] = validation.get("open_window_partner_names")
        attrs["actual_target_temperature"] = validation.get("actual_target_temperature")
        attrs["temperature_delta_to_expected"] = validation.get("temperature_delta")
        attrs.update(self._coordinator.get_pending_queue_details(self._address))
        if effective_week_profile:
            attrs["week_profile_lines"] = format_week_profile_lines(effective_week_profile)
            attrs.update(
                {
                    f"week_profile_{day}": value
                    for day, value in format_week_profile_by_day(effective_week_profile).items()
                }
            )
            if effective_week_profile != self._device.week_profile:
                attrs["week_profile_source"] = "linked_partner"
        state = self._coordinator.get_display_state(self._address)
        reported = state["reported"]
        for key in ("valve_position", "valve_position_reported_at", "reported_at", "battery_low",
                    "rf_error", "panel_locked", "display_actual_temperature", "heater_temperature"):
            if key in reported:
                attrs[key] = reported[key]
        attrs["until"] = state["until"].isoformat() if state["until"] else None
        attrs["boost_duration_min"] = reported.get("boost_duration") if state["mode"] == MODE_BOOST else None
        for key in ("requested_target_temperature", "reported_target_temperature", "requested_mode",
                    "reported_mode", "command_status", "state_source"):
            attrs[key] = state[key]
        attrs["temperature_command_status"] = state["command_status"]
        return attrs

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        state = self._coordinator.get_display_state(self._address)
        mode = state["mode"]
        if "hvac_mode" in kwargs:
            mode = {HVACMode.AUTO: MODE_AUTO, HVACMode.HEAT: MODE_MANUAL,
                    HVACMode.OFF: MODE_MANUAL}.get(kwargs["hvac_mode"])
            if kwargs["hvac_mode"] == HVACMode.OFF:
                temperature = TEMP_MIN
        if mode is None:
            raise ServiceValidationError("Betriebsmodus unbekannt; zuerst Automatik oder Manuell wählen.")
        until = state["until"] if mode == MODE_VACATION else None
        if mode == MODE_VACATION and (until is None or until.timestamp() <= datetime.now().timestamp()):
            raise ServiceValidationError("Urlaub benötigt eine gültige Endzeit (until).")
        await self._coordinator.async_set_temperature(
            self._address, temperature, mode=mode, until=until,
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._coordinator.async_set_temperature(self._address, TEMP_MIN, mode=MODE_MANUAL)
        elif hvac_mode == HVACMode.AUTO:
            await self._coordinator.async_set_temperature(self._address, 0.0, mode=MODE_AUTO)
        elif hvac_mode == HVACMode.HEAT:
            state = self._coordinator.get_display_state(self._address)
            temperature = state["target_temperature"]
            if state["hvac_mode"] == "off":
                temperature = self._device.last_normal_target or 20.0
            if temperature is None:
                raise ServiceValidationError("Solltemperatur unbekannt; zuerst eine Temperatur angeben.")
            await self._coordinator.async_set_temperature(self._address, temperature, mode=MODE_MANUAL)
        else:
            raise ServiceValidationError(f"Nicht unterstützter Betriebsmodus: {hvac_mode}")

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == "none":
            await self.async_set_hvac_mode(HVACMode.AUTO)
        elif preset_mode == "boost":
            await self._coordinator.async_set_temperature(self._address, 0.0, mode=MODE_BOOST)
        elif preset_mode == "away":
            state = self._coordinator.get_display_state(self._address)
            until = state["until"]
            if until is None or until.timestamp() <= datetime.now().timestamp():
                raise ServiceValidationError(
                    "Urlaub über cul_max.set_desired_temperature mit Temperatur und until starten."
                )
            if state["target_temperature"] is None:
                raise ServiceValidationError("Solltemperatur für Urlaub unbekannt.")
            await self._coordinator.async_set_temperature(
                self._address, state["target_temperature"], mode=MODE_VACATION, until=until,
            )
        else:
            raise ServiceValidationError(f"Nicht unterstütztes Preset: {preset_mode}")
