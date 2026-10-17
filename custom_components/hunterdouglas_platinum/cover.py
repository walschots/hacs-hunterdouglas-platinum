"""Cover entities: bottom rail (+ vanes as tilt), middle rail, and any other reported feature."""
from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_EXPOSE_UNKNOWN,
    CONF_INVERT_MIDDLE,
    CONF_SEPARATE_VANES,
    FEATURE_BOTTOM,
    FEATURE_MIDDLE,
)
from .coordinator import PlatinumCoordinator
from .entity import PlatinumShadeEntity, gateway_identifier


def to_pct(level: int | None) -> int | None:
    return None if level is None else round(level * 100 / 255)


def to_level(pct: float) -> int:
    return round(max(0.0, min(100.0, float(pct))) * 255 / 100)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PlatinumCoordinator = entry.runtime_data
    vane = coordinator.vane_feature
    expose_unknown = entry.options.get(CONF_EXPOSE_UNKNOWN, True)
    entities: list[CoverEntity] = []

    separate_vanes = entry.options.get(CONF_SEPARATE_VANES, True)

    for shade_id in coordinator.data.shades:
        features = coordinator.features_for(shade_id)
        tdbu = FEATURE_MIDDLE in features
        has_vanes = bool(vane) and vane in features
        entities.append(PlatinumBottomRail(coordinator, shade_id, tdbu, has_vanes))
        if tdbu:
            entities.append(PlatinumMiddleRail(coordinator, shade_id))
        if has_vanes and separate_vanes:
            entities.append(PlatinumVanes(coordinator, shade_id, vane))
        if expose_unknown:
            for feature in sorted(features - {FEATURE_BOTTOM, FEATURE_MIDDLE, vane}):
                entities.append(PlatinumRawFeature(coordinator, shade_id, feature))

    async_add_entities(entities)


class _PlatinumCover(PlatinumShadeEntity, CoverEntity):
    feature: str = FEATURE_BOTTOM
    invert = False
    role = "feature"  # read by the Lovelace card to group a blind's controls

    def __init__(self, coordinator: PlatinumCoordinator, shade_id: str) -> None:
        super().__init__(coordinator, shade_id)
        self._attr_unique_id = f"{gateway_identifier(coordinator)}_{shade_id}_{self.feature}"
        self._attr_supported_features = (
            CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.SET_POSITION
        )

    def _pct(self, feature: str, invert: bool = False) -> int | None:
        pct = to_pct(self.level(feature))
        return None if pct is None else (100 - pct if invert else pct)

    async def _move_pct(self, feature: str, pct: float, invert: bool = False) -> None:
        await self.coordinator.async_move(self.shade_id, feature, to_level(100 - pct if invert else pct))

    @property
    def current_cover_position(self) -> int | None:
        return self._pct(self.feature, self.invert)

    @property
    def is_closed(self) -> bool | None:
        pos = self.current_cover_position
        return None if pos is None else pos == 0

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._move_pct(self.feature, 100, self.invert)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._move_pct(self.feature, 0, self.invert)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        await self._move_pct(self.feature, kwargs[ATTR_POSITION], self.invert)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "shade_id": self.shade_id,
            "feature": self.feature,
            "raw_level": self.level(self.feature),
            "platinum_role": self.role,
        }


class PlatinumBottomRail(_PlatinumCover):
    """Main shade position; vanes exposed as tilt when the vane code is configured."""

    feature = FEATURE_BOTTOM
    role = "bottom"

    def __init__(self, coordinator: PlatinumCoordinator, shade_id: str, tdbu: bool, has_vanes: bool) -> None:
        super().__init__(coordinator, shade_id)
        self._vane = coordinator.vane_feature if has_vanes else ""
        self._attr_name = "Bottom rail" if tdbu else None
        self._attr_device_class = CoverDeviceClass.BLIND if has_vanes else CoverDeviceClass.SHADE
        if has_vanes:
            self._attr_supported_features |= (
                CoverEntityFeature.OPEN_TILT
                | CoverEntityFeature.CLOSE_TILT
                | CoverEntityFeature.SET_TILT_POSITION
            )

    @property
    def current_cover_tilt_position(self) -> int | None:
        return self._pct(self._vane) if self._vane else None

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        await self._move_pct(self._vane, 100)

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        await self._move_pct(self._vane, 0)

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        await self._move_pct(self._vane, kwargs[ATTR_TILT_POSITION])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        if self._vane:
            attrs["vane_feature"] = self._vane
            attrs["raw_vane_level"] = self.level(self._vane)
        return attrs


class PlatinumMiddleRail(_PlatinumCover):
    """Top-down / bottom-up middle rail. 100% = rail fully lowered (top of window open)."""

    feature = FEATURE_MIDDLE
    role = "middle"
    _attr_name = "Middle rail"
    _attr_device_class = CoverDeviceClass.SHADE

    def __init__(self, coordinator: PlatinumCoordinator, shade_id: str) -> None:
        super().__init__(coordinator, shade_id)
        self.invert = bool(coordinator.config_entry.options.get(CONF_INVERT_MIDDLE, False))


class PlatinumVanes(_PlatinumCover):
    """Vanes as their own cover, so any dashboard card shows a plain slider for them.

    Position 0 = vanes closed, 100 = vanes fully open.
    """

    _attr_name = "Vanes"
    role = "vanes"
    _attr_icon = "mdi:blinds-horizontal"
    _attr_device_class = CoverDeviceClass.BLIND

    def __init__(self, coordinator: PlatinumCoordinator, shade_id: str, feature: str) -> None:
        self.feature = feature
        super().__init__(coordinator, shade_id)
        self._attr_unique_id = f"{gateway_identifier(coordinator)}_{shade_id}_vanes"


class PlatinumRawFeature(_PlatinumCover):
    """Any other feature the gateway reports (useful for finding the vane code)."""

    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: PlatinumCoordinator, shade_id: str, feature: str) -> None:
        self.feature = feature
        super().__init__(coordinator, shade_id)
        self._attr_name = f"Feature {feature}"
