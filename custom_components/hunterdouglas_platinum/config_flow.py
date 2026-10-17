"""Config flow for Hunter Douglas Platinum."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback

from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_EXPOSE_UNKNOWN,
    CONF_INVERT_MIDDLE,
    CONF_SCAN_INTERVAL,
    CONF_SEPARATE_VANES,
    CONF_TDBU_SHADES,
    CONF_VANE_FEATURE,
    CONF_VANE_SHADES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VANE_FEATURE,
    DOMAIN,
)
from .gateway import DEFAULT_PORT, PlatinumError, PlatinumGateway


class PlatinumConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            try:
                data = await PlatinumGateway(host, port).get_data()
            except PlatinumError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(data.mac or f"{host}:{port}")
                self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
                return self.async_create_entry(
                    title=data.house_name or f"Platinum Gateway ({host})",
                    data={CONF_HOST: host, CONF_PORT: port},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PlatinumOptionsFlow()


class PlatinumOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            vane = str(user_input.get(CONF_VANE_FEATURE, "")).strip()
            if vane and not (vane.isdigit() and 0 <= int(vane) <= 99):
                errors[CONF_VANE_FEATURE] = "invalid_feature"
            else:
                user_input[CONF_VANE_FEATURE] = vane.zfill(2) if vane else ""
                return self.async_create_entry(data=user_input)

        opts = self.config_entry.options
        shades = self._shade_choices()
        schema: dict = {
            vol.Optional(
                CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ): vol.All(int, vol.Range(min=15, max=3600)),
            vol.Optional(
                CONF_VANE_FEATURE,
                description={"suggested_value": opts.get(CONF_VANE_FEATURE, DEFAULT_VANE_FEATURE)},
            ): str,
        }
        if shades:
            schema[vol.Optional(CONF_TDBU_SHADES, default=[s for s in opts.get(CONF_TDBU_SHADES, []) if s in shades])] = cv.multi_select(shades)
            schema[vol.Optional(CONF_VANE_SHADES, default=[s for s in opts.get(CONF_VANE_SHADES, []) if s in shades])] = cv.multi_select(shades)
        schema.update(
            {
                vol.Optional(CONF_SEPARATE_VANES, default=opts.get(CONF_SEPARATE_VANES, True)): bool,
                vol.Optional(CONF_INVERT_MIDDLE, default=opts.get(CONF_INVERT_MIDDLE, False)): bool,
                vol.Optional(CONF_EXPOSE_UNKNOWN, default=opts.get(CONF_EXPOSE_UNKNOWN, True)): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema), errors=errors)

    def _shade_choices(self) -> dict[str, str]:
        """shade id -> 'Room · Shade' label, from the running coordinator."""
        coordinator = getattr(self.config_entry, "runtime_data", None)
        data = getattr(coordinator, "data", None)
        if data is None:
            return {}
        choices = {}
        for shade in sorted(data.shades.values(), key=lambda s: (s.room_id, s.id)):
            room = data.rooms.get(shade.room_id)
            choices[shade.id] = f"{room.name} · {shade.name}" if room else shade.name
        return choices
