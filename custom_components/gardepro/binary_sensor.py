"""Binary sensor platform for GardePro Trail Camera integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GardeProCoordinator
from .sensor import _firmware


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GardePro binary sensor entities."""
    coordinator: GardeProCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[GardeProOnlineSensor] = []
    for device_id in coordinator.get_device_ids():
        entities.append(GardeProOnlineSensor(coordinator, device_id))

    async_add_entities(entities)


class GardeProOnlineSensor(
    CoordinatorEntity[GardeProCoordinator], BinarySensorEntity
):
    """Binary sensor indicating whether the camera is online."""

    _attr_has_entity_name = True
    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self,
        coordinator: GardeProCoordinator,
        device_id: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_online"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info for device registry."""
        dev = self.coordinator.get_device_data(self._device_id)
        if not dev:
            return {}
        name = dev.get("name") or self._device_id
        model = dev.get("model", "Trail Camera")
        product_code = dev.get("productCode", "")

        info: dict[str, Any] = {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": f"GardePro {name}",
            "manufacturer": "GardePro",
            "model": model,
        }
        if product_code:
            info["serial_number"] = product_code
        fw = _firmware(dev)
        if fw and fw != "unknown":
            info["sw_version"] = fw
        return info

    @property
    def is_on(self) -> bool | None:
        """Return True if the camera is online."""
        dev = self.coordinator.get_device_data(self._device_id)
        if not dev:
            return None
        return bool(dev.get("onlineStatus", 0))

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        return (
            super().available
            and self.coordinator.get_device_data(self._device_id) is not None
        )
