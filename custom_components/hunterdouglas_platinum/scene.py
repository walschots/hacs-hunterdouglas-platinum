"""Scenes stored in the Platinum gateway."""
from __future__ import annotations

from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PlatinumCoordinator
from .entity import gateway_identifier


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PlatinumCoordinator = entry.runtime_data
    async_add_entities(PlatinumScene(coordinator, sid) for sid in coordinator.data.scenes)


class PlatinumScene(CoordinatorEntity[PlatinumCoordinator], Scene):
    _attr_has_entity_name = True

    def __init__(self, coordinator: PlatinumCoordinator, scene_id: str) -> None:
        super().__init__(coordinator)
        self.scene_id = scene_id
        gw = gateway_identifier(coordinator)
        self._attr_unique_id = f"{gw}_scene_{scene_id}"
        self._attr_name = coordinator.data.scenes[scene_id].name
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, gw)})

    async def async_activate(self, **kwargs: Any) -> None:
        await self.coordinator.async_scene(self.scene_id)
