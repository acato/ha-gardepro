"""Config flow for GardePro Trail Camera integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_BASE, API_HEADERS, CONF_EMAIL, CONF_PASSWORD, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _validate_credentials(
    session: aiohttp.ClientSession, email: str, password: str
) -> dict[str, Any]:
    """Validate GardePro credentials and return login data.

    Returns dict with token, userId on success.
    Raises ValueError on auth failure, aiohttp.ClientError on network failure.
    """
    headers = {**API_HEADERS}
    payload = {
        "email": email,
        "password": password,
        "currency": 0,
        "serverZone": "US",
        "country": "US",
    }
    async with session.post(
        f"{API_BASE}/user/login/email",
        headers=headers,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=15),
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()

    if not data.get("success"):
        code = data.get("code", "unknown")
        _LOGGER.error("GardePro login failed (code %s): %s", code, data.get("msg", ""))
        raise ValueError(f"Login failed: code {code}")

    return data["data"]


class GardeProConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GardePro."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: email + password."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            # Prevent duplicate entries for the same account
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            try:
                login_data = await _validate_credentials(session, email, password)
            except ValueError:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during GardePro login")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"GardePro ({email})",
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                        "user_id": login_data["userId"],
                        "token": login_data["token"],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
