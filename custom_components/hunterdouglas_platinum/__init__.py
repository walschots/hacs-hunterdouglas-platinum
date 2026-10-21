"""Hunter Douglas Platinum gateway integration.

Full control of Platinum (PowerRise) shades: bottom rail, top-down/bottom-up
middle rail, vanes (as cover tilt), and gateway scenes.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    ATTR_FEATURE,
    ATTR_LEVEL,
    ATTR_POSITION,
    ATTR_SHADE_ID,
    DOMAIN,
    MANUFACTURER,
    SERVICE_REFRESH,
    SERVICE_SET_FEATURE,
)
from .coordinator import PlatinumCoordinator
from .gateway import DEFAULT_PORT, PlatinumError, PlatinumGateway

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.COVER, Platform.SCENE]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SET_FEATURE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(ATTR_SHADE_ID): vol.All(vol.Coerce(int), vol.Range(min=0, max=99)),
            vol.Required(ATTR_FEATURE): vol.All(vol.Coerce(int), vol.Range(min=0, max=99)),
            vol.Exclusive(ATTR_POSITION, "pos"): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
            vol.Exclusive(ATTR_LEVEL, "pos"): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
            vol.Optional("config_entry_id"): cv.string,
        }
    ),
    cv.has_at_least_one_key(ATTR_POSITION, ATTR_LEVEL),
)


def _coordinator_for(hass: HomeAssistant, entry_id: str | None) -> PlatinumCoordinator:
    entries = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED
    ]
    if entry_id:
        entries = [e for e in entries if e.entry_id == entry_id]
    if not entries:
        raise ServiceValidationError("No loaded Hunter Douglas Platinum gateway found")
    return entries[0].runtime_data


CARD_URL = f"/{DOMAIN}/hunterdouglas-platinum-card.js"


async def _async_add_lovelace_resource(hass: HomeAssistant, url: str) -> bool:
    """Add (or update) the card as a dashboard resource. Returns False if not possible.

    Dashboard resources are loaded before cards are drawn, so the card is defined on
    a cold start of the companion app (an extra_js_url can arrive too late and leave
    'Configuration error' boxes until the page is refreshed).
    """
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return False
    if isinstance(lovelace, dict):  # older Home Assistant versions
        resources = lovelace.get("resources")
        mode = lovelace.get("resource_mode", lovelace.get("mode"))
    else:
        resources = getattr(lovelace, "resources", None)
        mode = getattr(lovelace, "resource_mode", None) or getattr(lovelace, "mode", None)
    if resources is None or mode != "storage":
        return False
    if not getattr(resources, "loaded", True):
        await resources.async_load()
        resources.loaded = True
    for item in resources.async_items():
        if str(item.get("url", "")).split("?")[0] == CARD_URL:
            if item.get("url") != url:
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
            return True
    await resources.async_create_item({"res_type": "module", "url": url})
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the dashboard card from this integration and make every dashboard load it."""
    from homeassistant.components.http import StaticPathConfig

    path = Path(__file__).parent / "frontend" / "hunterdouglas-platinum-card.js"
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), True)])
    # The URL carries a hash of the file's contents, so browsers and the companion app
    # may cache it (cache_headers=True above), and every new card version gets a new URL.
    digest = await hass.async_add_executor_job(lambda: hashlib.sha1(path.read_bytes()).hexdigest()[:10])
    url = f"{CARD_URL}?v={digest}"

    async def _register(_event=None) -> None:
        try:
            if await _async_add_lovelace_resource(hass, url):
                return
        except Exception:  # noqa: BLE001 - fall back to the extra JS URL below
            _LOGGER.debug("Could not add the card as a dashboard resource", exc_info=True)
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, url)

    if hass.state is CoreState.running:
        await _register()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    try:
        await _async_register_card(hass)
    except Exception:  # noqa: BLE001 - the integration still works without the card
        _LOGGER.exception("Could not register the Hunter Douglas Platinum card")

    async def set_feature(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call.data.get("config_entry_id"))
        level = call.data.get(ATTR_LEVEL)
        if level is None:
            level = round(call.data[ATTR_POSITION] * 255 / 100)
        shade_id = f"{call.data[ATTR_SHADE_ID]:02d}"
        feature = f"{call.data[ATTR_FEATURE]:02d}"
        try:
            await coordinator.async_move(shade_id, feature, level)
        except PlatinumError as err:
            raise HomeAssistantError(str(err)) from err

    async def refresh(call: ServiceCall) -> dict:
        coordinator = _coordinator_for(hass, call.data.get("config_entry_id"))
        await coordinator.async_refresh()
        data = coordinator.data
        return {
            "rooms": {r.id: {"name": r.name, "shade_type": r.shade_type, "shades": r.shade_ids} for r in data.rooms.values()},
            "shades": {
                s.id: {"name": s.name, "room": s.room_id, "features": dict(sorted(s.positions.items()))}
                for s in data.shades.values()
            },
            "scenes": {s.id: s.name for s in data.scenes.values()},
            "raw": data.raw_lines,
        }

    hass.services.async_register(DOMAIN, SERVICE_SET_FEATURE, set_feature, schema=SET_FEATURE_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        refresh,
        schema=vol.Schema({vol.Optional("config_entry_id"): cv.string}),
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    gateway = PlatinumGateway(entry.data[CONF_HOST], entry.data.get(CONF_PORT, DEFAULT_PORT))
    coordinator = PlatinumCoordinator(hass, entry, gateway)
    await coordinator.async_load_known()
    await coordinator.async_config_entry_first_refresh()  # raises ConfigEntryNotReady
    entry.runtime_data = coordinator

    data = coordinator.data
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, data.mac or entry.entry_id)},
        manufacturer=MANUFACTURER,
        model="Platinum Gateway",
        name=data.house_name or "Platinum Gateway",
        sw_version=data.firmware or None,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
