"""Polling coordinator for the Platinum gateway."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_TDBU_SHADES,
    CONF_VANE_FEATURE,
    CONF_VANE_SHADES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VANE_FEATURE,
    DOMAIN,
    FEATURE_BOTTOM,
    FEATURE_MIDDLE,
    TDBU_ROOM_TYPES,
)
from .gateway import PlatinumData, PlatinumError, PlatinumGateway

_LOGGER = logging.getLogger(__name__)


class PlatinumCoordinator(DataUpdateCoordinator[PlatinumData]):
    """Fetches $dat periodically and applies optimistic updates after moves."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, gateway: PlatinumGateway) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.gateway = gateway
        self._refresh_handle: asyncio.TimerHandle | None = None

    async def _async_update_data(self) -> PlatinumData:
        try:
            return await self.gateway.get_data()
        except PlatinumError as err:
            raise UpdateFailed(str(err)) from err

    @property
    def vane_feature(self) -> str:
        raw = str(self.config_entry.options.get(CONF_VANE_FEATURE, DEFAULT_VANE_FEATURE) or "").strip()
        return raw.zfill(2) if raw else ""

    @property
    def tdbu_shades(self) -> set[str]:
        return set(self.config_entry.options.get(CONF_TDBU_SHADES, []))

    @property
    def vane_shades(self) -> set[str]:
        return set(self.config_entry.options.get(CONF_VANE_SHADES, []))

    def features_for(self, shade_id: str) -> set[str]:
        """Features a shade supports: what the gateway reports, plus implied/forced ones."""
        shade = self.data.shades[shade_id]
        features = set(shade.positions) | {FEATURE_BOTTOM}
        room = self.data.rooms.get(shade.room_id)
        if (room and room.shade_type in TDBU_ROOM_TYPES) or shade_id in self.tdbu_shades:
            features.add(FEATURE_MIDDLE)
        if self.vane_feature and shade_id in self.vane_shades:
            features.add(self.vane_feature)
        return features

    async def async_move(self, shade_id: str, feature: str, level: int) -> None:
        level = max(0, min(255, int(level)))
        await self.gateway.queue_move(shade_id, feature, level)
        # Platinum shades are one-way RF: the gateway just stores the last command,
        # so the commanded level is the best state we will ever get.
        if shade := self.data.shades.get(shade_id):
            shade.positions[feature] = level
        self.async_update_listeners()
        self._schedule_refresh()

    async def async_scene(self, scene_id: str) -> None:
        await self.gateway.activate_scene(scene_id)
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        if self._refresh_handle:
            self._refresh_handle.cancel()
        self._refresh_handle = self.hass.loop.call_later(
            5, lambda: self.hass.async_create_task(self.async_request_refresh())
        )
