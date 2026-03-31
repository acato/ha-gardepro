"""Sensor platform for GardePro Trail Camera integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GardeProCoordinator


@dataclass(frozen=True, kw_only=True)
class GardeProSensorEntityDescription(SensorEntityDescription):
    """Describes a GardePro sensor entity."""

    value_fn: Callable[[dict[str, Any]], Any]


def _sd_used_gb(dev: dict[str, Any]) -> float:
    """Calculate SD used in GB."""
    return round(dev.get("sdUsed", 0) / 1048576, 1)


def _sd_percent(dev: dict[str, Any]) -> float:
    """Calculate SD usage percentage."""
    total = dev.get("sdTotal", 0)
    used = dev.get("sdUsed", 0)
    if total <= 0:
        return 0.0
    return round(used / total * 100, 1)


def _firmware(dev: dict[str, Any]) -> str:
    """Extract firmware version string."""
    version = dev.get("version", "")
    if version:
        return version.split("\n")[0]
    return "unknown"


SENSOR_DESCRIPTIONS: tuple[GardeProSensorEntityDescription, ...] = (
    GardeProSensorEntityDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda dev: dev.get("battery", 0),
    ),
    GardeProSensorEntityDescription(
        key="sd_used",
        translation_key="sd_used",
        native_unit_of_measurement="GB",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:micro-sd",
        value_fn=_sd_used_gb,
    ),
    GardeProSensorEntityDescription(
        key="sd_percent",
        translation_key="sd_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:micro-sd",
        value_fn=_sd_percent,
    ),
    GardeProSensorEntityDescription(
        key="signal",
        translation_key="signal",
        native_unit_of_measurement="bars",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:signal-cellular-3",
        value_fn=lambda dev: dev.get("signals", 0),
    ),
    GardeProSensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda dev: dev.get("temperature", 0),
    ),
    GardeProSensorEntityDescription(
        key="photos",
        translation_key="photos",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:image-multiple",
        value_fn=lambda dev: dev.get("picNum", 0),
    ),
    GardeProSensorEntityDescription(
        key="videos",
        translation_key="videos",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:video-box",
        value_fn=lambda dev: dev.get("videoNum", 0),
    ),
    GardeProSensorEntityDescription(
        key="plan_days",
        translation_key="plan_days",
        native_unit_of_measurement="days",
        icon="mdi:calendar-clock",
        value_fn=lambda dev: dev.get("daysLeft", 0),
    ),
    GardeProSensorEntityDescription(
        key="firmware",
        translation_key="firmware",
        icon="mdi:chip",
        value_fn=_firmware,
    ),
    GardeProSensorEntityDescription(
        key="last_activity",
        translation_key="last_activity",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-outline",
        value_fn=lambda dev: dev.get("lastModifyTime") or None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GardePro sensor entities."""
    coordinator: GardeProCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[GardeProSensor] = []
    for device_id in coordinator.get_device_ids():
        for description in SENSOR_DESCRIPTIONS:
            entities.append(
                GardeProSensor(coordinator, device_id, description)
            )

    async_add_entities(entities)


class GardeProSensor(CoordinatorEntity[GardeProCoordinator], SensorEntity):
    """Representation of a GardePro sensor."""

    entity_description: GardeProSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GardeProCoordinator,
        device_id: str,
        description: GardeProSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_{description.key}"

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
    def native_value(self) -> Any:
        """Return the sensor value."""
        dev = self.coordinator.get_device_data(self._device_id)
        if not dev:
            return None
        return self.entity_description.value_fn(dev)

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        return (
            super().available
            and self.coordinator.get_device_data(self._device_id) is not None
        )
