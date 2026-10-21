"""Polling coordinator for the Platinum gateway."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
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
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
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
        # Last known level per shade/feature. The gateway omits features it has no
        # stored level for (often the middle rail and vanes), so without this every
        # poll would wipe the level we last commanded and the entity goes "unknown".
        self._known: dict[str, dict[str, int]] = {}
        self._store: Store[dict[str, dict[str, int]]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.positions"
        )

    async def async_load_known(self) -> None:
        """Restore last known levels saved before the last restart."""
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._known = {
                str(shade): {str(f): int(lvl) for f, lvl in feats.items()}
                for shade, feats in stored.items()
                if isinstance(feats, dict)
            }

    def _remember(self, shade_id: str, feature: str, level: int) -> None:
        feats = self._known.setdefault(shade_id, {})
        if feats.get(feature) != level:
            feats[feature] = level
            self._store.async_delay_save(lambda: self._known, STORAGE_SAVE_DELAY)

    async def _async_update_data(self) -> PlatinumData:
        try:
            data = await self.gateway.get_data()
        except PlatinumError as err:
            raise UpdateFailed(str(err)) from err
        for shade in data.shades.values():
            # What the gateway reports wins; fill gaps from the last known level.
            for feature, level in shade.positions.items():
                self._remember(shade.id, feature, level)
            for feature, level in self._known.get(shade.id, {}).items():
                shade.positions.setdefault(feature, level)
        return data

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
        self._remember(shade_id, feature, level)
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
