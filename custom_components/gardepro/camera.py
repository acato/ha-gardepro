"""Camera platform for GardePro Trail Camera integration."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GardeProCoordinator
from .sensor import _firmware

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up GardePro camera entities."""
    coordinator: GardeProCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[GardeProCamera] = []
    for device_id in coordinator.get_device_ids():
        entities.append(GardeProCamera(coordinator, device_id))

    async_add_entities(entities)


class GardeProCamera(CoordinatorEntity[GardeProCoordinator], Camera):
    """Camera entity showing the latest trail cam capture."""

    _attr_has_entity_name = True
    _attr_translation_key = "latest_capture"

    def __init__(
        self,
        coordinator: GardeProCoordinator,
        device_id: str,
    ) -> None:
        """Initialize the camera."""
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_camera"
        self._current_path: str | None = None

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

    def _get_image_path(self) -> Path | None:
        """Get the path to the latest image file."""
        dev = self.coordinator.get_device_data(self._device_id)
        if not dev:
            return None

        # Use latest_image from coordinator data
        latest = dev.get("latest_image")
        if latest:
            path = Path(latest)
            if path.exists():
                return path

        # Fallback: check for latest.jpg in the camera media directory
        cam_name = self.coordinator._get_camera_name(self._device_id)
        latest_path = self.coordinator.get_media_root() / cam_name / "latest.jpg"
        if latest_path.exists():
            return latest_path

        return None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the latest camera image."""

        def _read_image() -> bytes | None:
            path = self._get_image_path()
            if path is None:
                return None
            try:
                return path.read_bytes()
            except OSError as err:
                _LOGGER.error("Error reading camera image %s: %s", path, err)
                return None

        return await self.hass.async_add_executor_job(_read_image)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {}
        path = self._get_image_path()
        if path:
            attrs["file_path"] = str(path)
        return attrs

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            super().available
            and self.coordinator.get_device_data(self._device_id) is not None
        )
