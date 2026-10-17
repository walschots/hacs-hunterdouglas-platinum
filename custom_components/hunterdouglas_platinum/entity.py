"""Base entity for Platinum shades."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import PlatinumCoordinator


def gateway_identifier(coordinator: PlatinumCoordinator) -> str:
    return coordinator.data.mac or coordinator.config_entry.entry_id


class PlatinumShadeEntity(CoordinatorEntity[PlatinumCoordinator]):
    """An entity that belongs to one physical shade (one HA device per shade)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PlatinumCoordinator, shade_id: str) -> None:
        super().__init__(coordinator)
        self.shade_id = shade_id
        gw = gateway_identifier(coordinator)
        shade = coordinator.data.shades[shade_id]
        room = coordinator.data.rooms.get(shade.room_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{gw}_shade_{shade_id}")},
            name=shade.name,
            manufacturer=MANUFACTURER,
            model="Platinum shade",
            suggested_area=room.name if room else None,
            via_device=(DOMAIN, gw),
        )

    @property
    def shade(self):
        return self.coordinator.data.shades.get(self.shade_id)

    @property
    def available(self) -> bool:
        return super().available and self.shade is not None

    def level(self, feature: str) -> int | None:
        shade = self.shade
        return None if shade is None else shade.positions.get(feature)
