"""DataUpdateCoordinator for GardePro Trail Camera integration."""
from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
import boto3
from botocore.exceptions import ClientError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_BASE,
    API_HEADERS,
    API_TOKEN_LIFETIME,
    DOMAIN,
    MEDIA_DIR,
    S3_KEY_PATTERN,
    S3_TOKEN_LIFETIME,
    SCAN_INTERVAL_MEDIA,
    SCAN_INTERVAL_TELEMETRY,
)

_LOGGER = logging.getLogger(__name__)


class GardeProCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls GardePro cloud for media and telemetry.

    Data structure:
    {
        "devices": {
            "<simDeviceId>": {
                "name": str,
                "model": str,
                "productCode": str (IMEI),
                "battery": int,
                "sdTotal": int,
                "sdUsed": int,
                "signals": int,
                "temperature": int,
                "picNum": int,
                "videoNum": int,
                "daysLeft": int,
                "version": str,
                "onlineStatus": int,
                "lastModifyTime": str,
                "latest_image": str | None,  # local file path
            },
            ...
        },
        "last_telemetry": str (ISO timestamp),
    }
    """

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL_MEDIA,
        )
        self._email: str = entry.data["email"]
        self._password: str = entry.data["password"]
        self._user_id: int = entry.data["user_id"]
        self._token: str = entry.data["token"]

        self._token_expiry: datetime | None = None
        self._s3_creds: dict[str, Any] | None = None
        self._s3_expiry: datetime | None = None

        self._last_message_id: int = 0
        self._last_telemetry: datetime | None = None
        self._poll_count: int = 0

        # Media storage path
        self._media_root = Path(hass.config.media_dirs.get("local", "/media")) / MEDIA_DIR

    # ------------------------------------------------------------------
    # API helpers (run in executor since we use aiohttp for HTTP)
    # ------------------------------------------------------------------

    async def _api_request(
        self,
        method: str,
        path: str,
        json_data: dict | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated API request."""
        await self._ensure_api_token()

        headers = {
            **API_HEADERS,
            "authorization": self._token,
            "app_userid": str(self._user_id),
        }
        session = async_get_clientsession(self.hass)
        timeout = aiohttp.ClientTimeout(total=15)

        try:
            if method == "GET":
                async with session.get(
                    f"{API_BASE}{path}", headers=headers, timeout=timeout
                ) as resp:
                    if resp.status == 401:
                        self._token_expiry = None  # force refresh
                        raise UpdateFailed("API token expired (401)")
                    resp.raise_for_status()
                    return await resp.json(content_type=None)
            else:
                async with session.post(
                    f"{API_BASE}{path}",
                    headers=headers,
                    json=json_data or {},
                    timeout=timeout,
                ) as resp:
                    if resp.status == 401:
                        self._token_expiry = None
                        raise UpdateFailed("API token expired (401)")
                    resp.raise_for_status()
                    return await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"API request failed: {err}") from err

    async def _ensure_api_token(self) -> None:
        """Refresh API token if expired."""
        now = datetime.now(timezone.utc)
        if self._token_expiry and now < self._token_expiry:
            return

        _LOGGER.debug("Refreshing GardePro API token")
        session = async_get_clientsession(self.hass)
        headers = {**API_HEADERS}
        payload = {
            "email": self._email,
            "password": self._password,
            "currency": 0,
            "serverZone": "US",
            "country": "US",
        }
        timeout = aiohttp.ClientTimeout(total=15)

        try:
            async with session.post(
                f"{API_BASE}/user/login/email",
                headers=headers,
                json=payload,
                timeout=timeout,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"GardePro login failed: {err}") from err

        if not data.get("success"):
            raise UpdateFailed(f"GardePro login failed: code {data.get('code')}")

        self._token = data["data"]["token"]
        self._user_id = data["data"]["userId"]
        self._token_expiry = now + API_TOKEN_LIFETIME
        _LOGGER.debug("API token refreshed, expires %s", self._token_expiry)

    async def _ensure_s3_credentials(self) -> None:
        """Refresh S3 federation token if expired."""
        now = datetime.now(timezone.utc)
        if self._s3_creds and self._s3_expiry and now < self._s3_expiry:
            return

        _LOGGER.debug("Refreshing S3 federation token")
        data = await self._api_request(
            "GET",
            f"/device/s3/federationtoken/user/{self._user_id}?dynamic=1",
        )
        if not data.get("success"):
            raise UpdateFailed(f"S3 token request failed: {data}")

        self._s3_creds = data["data"]
        self._s3_expiry = now + S3_TOKEN_LIFETIME
        _LOGGER.debug("S3 token refreshed, bucket=%s", self._s3_creds.get("bucketName"))

    # ------------------------------------------------------------------
    # Device list / telemetry
    # ------------------------------------------------------------------

    async def _fetch_devices(self) -> list[dict[str, Any]]:
        """Fetch device list with status."""
        data = await self._api_request(
            "GET",
            f"/v2/device/list/withstatus/{self._user_id}?withTags=1",
        )
        if not data.get("success"):
            raise UpdateFailed(f"Device list failed: {data}")
        return data.get("data", [])

    # ------------------------------------------------------------------
    # Notification polling for new media
    # ------------------------------------------------------------------

    async def _fetch_messages(self) -> list[dict[str, Any]]:
        """Fetch recent notification messages."""
        data = await self._api_request(
            "GET",
            f"/user/messages/{self._user_id}/0/10",
        )
        if not data.get("success"):
            code = data.get("code")
            if code == 2205:
                # Auth expired
                self._token_expiry = None
                raise UpdateFailed("Auth expired (code 2205)")
            _LOGGER.warning("Messages API returned non-success: %s", data)
            return []
        return data.get("data", [])

    async def _download_media(self, s3_key: str, device_id: str) -> str | None:
        """Download a media file from S3 to local storage. Returns local path or None."""
        parsed = self._parse_s3_key(s3_key)
        if not parsed:
            return None

        # Get camera name from current device data
        cam_name = self._get_camera_name(device_id)
        dest_dir = self._media_root / cam_name / parsed["date"]
        dest = dest_dir / f"{parsed['time']}_{parsed['media_num']}.{parsed['ext']}"

        if dest.exists():
            return str(dest)

        await self._ensure_s3_credentials()

        # Run S3 download in executor (boto3 is synchronous)
        def _do_download() -> str | None:
            creds = self._s3_creds
            s3 = boto3.client(
                "s3",
                aws_access_key_id=creds["accessKeyId"],
                aws_secret_access_key=creds["secretAccessKey"],
                aws_session_token=creds["sessionToken"],
                region_name=creds.get("regionId", "us-west-2"),
            )
            bucket = creds.get("bucketName", "trailcamera-media")

            dest_dir.mkdir(parents=True, exist_ok=True)

            # Try bare key, then with trailcamera-media/ prefix
            for key_attempt in [s3_key, f"trailcamera-media/{s3_key}"]:
                try:
                    s3.download_file(bucket, key_attempt, str(dest))
                    _LOGGER.debug("Downloaded %s -> %s", key_attempt, dest.name)

                    # Update latest.jpg for image files
                    if parsed["ext"] == "jpg":
                        latest = self._media_root / cam_name / "latest.jpg"
                        self._media_root.joinpath(cam_name).mkdir(
                            parents=True, exist_ok=True
                        )
                        try:
                            shutil.copy2(str(dest), str(latest))
                        except OSError:
                            pass

                    return str(dest)
                except ClientError as exc:
                    error_code = exc.response.get("Error", {}).get("Code", "")
                    if error_code == "ExpiredToken":
                        _LOGGER.warning("S3 token expired during download")
                        self._s3_expiry = None
                        return None
                    if error_code == "NoSuchKey":
                        continue
                    _LOGGER.error("S3 download error: %s", exc)
                    return None

            _LOGGER.warning("S3 key not found in bucket: %s", s3_key)
            return None

        return await self.hass.async_add_executor_job(_do_download)

    # ------------------------------------------------------------------
    # Main update
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from GardePro cloud.

        Every poll: check notifications for new media.
        Every 10th poll (~5 min): also refresh full device telemetry.
        """
        self._poll_count += 1
        existing = self.data or {"devices": {}, "last_telemetry": None}

        # Always poll notifications for new media
        try:
            messages = await self._fetch_messages()
            await self._process_messages(messages, existing)
        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.error("Error polling notifications: %s", err)

        # Refresh full telemetry every ~5 minutes (10 polls * 30s)
        refresh_telemetry = (
            self._poll_count % 10 == 1  # first poll + every 10th
            or not existing.get("devices")
        )

        if refresh_telemetry:
            try:
                devices = await self._fetch_devices()
                for dev in devices:
                    did = str(dev.get("simDeviceId", ""))
                    if not did:
                        continue

                    # Preserve latest_image from previous data
                    prev = existing.get("devices", {}).get(did, {})
                    dev_data = {
                        "name": dev.get("name") or dev.get("productCode") or did,
                        "model": dev.get("model", ""),
                        "productCode": dev.get("productCode", ""),
                        "battery": dev.get("battery", 0),
                        "sdTotal": dev.get("sdTotal", 0),
                        "sdUsed": dev.get("sdUsed", 0),
                        "signals": dev.get("signals", 0),
                        "temperature": dev.get("temperature", 0),
                        "picNum": dev.get("picNum", 0),
                        "videoNum": dev.get("videoNum", 0),
                        "daysLeft": dev.get("daysLeft", 0),
                        "version": dev.get("version", ""),
                        "onlineStatus": dev.get("onlineStatus", 0),
                        "lastModifyTime": dev.get("lastModifyTime", ""),
                        "latest_image": prev.get("latest_image"),
                        "simDeviceId": did,
                    }
                    existing["devices"][did] = dev_data

                existing["last_telemetry"] = datetime.now(timezone.utc).isoformat()
            except UpdateFailed:
                raise
            except Exception as err:
                _LOGGER.error("Error fetching device telemetry: %s", err)

        return existing

    async def _process_messages(
        self, messages: list[dict[str, Any]], data: dict[str, Any]
    ) -> None:
        """Process new notification messages, download media."""
        new_msgs = [m for m in messages if m.get("id", 0) > self._last_message_id]
        if not new_msgs:
            return

        new_msgs.sort(key=lambda m: m["id"])
        _LOGGER.info("Processing %d new GardePro message(s)", len(new_msgs))

        for msg in new_msgs:
            msg_id = msg["id"]
            msg_type = msg.get("type")

            if msg_type == 2002:
                # New media notification
                content = msg.get("content", "")
                s3_key = content
                if s3_key.startswith("trailcamera-media/"):
                    s3_key = s3_key[len("trailcamera-media/"):]

                parsed = self._parse_s3_key(s3_key)
                if parsed:
                    device_id = parsed["device_id"]
                    local_path = await self._download_media(s3_key, device_id)
                    if local_path and device_id in data.get("devices", {}):
                        if parsed["ext"] == "jpg":
                            cam_name = self._get_camera_name(device_id)
                            latest = str(self._media_root / cam_name / "latest.jpg")
                            data["devices"][device_id]["latest_image"] = latest

                            # Fire event for automations
                            self.hass.bus.async_fire(
                                f"{DOMAIN}_new_capture",
                                {
                                    "device_id": device_id,
                                    "camera_name": cam_name,
                                    "file_path": local_path,
                                },
                            )

            self._last_message_id = msg_id

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_camera_name(self, device_id: str) -> str:
        """Get camera name from device data, falling back to device_id."""
        devices = (self.data or {}).get("devices", {})
        dev = devices.get(device_id)
        if dev and dev.get("name"):
            # Sanitize for filesystem: lowercase, replace spaces with underscores
            name = dev["name"].lower().replace(" ", "_")
            # Remove any non-alphanumeric chars except underscore/dash
            return re.sub(r"[^a-z0-9_-]", "", name)
        return device_id

    @staticmethod
    def _parse_s3_key(key: str) -> dict[str, Any] | None:
        """Parse an S3 key into components."""
        m = re.match(S3_KEY_PATTERN, key, re.IGNORECASE)
        if not m:
            return None
        device_id, timestamp_str, media_num, ext = m.groups()
        dt = datetime.strptime(timestamp_str, "%Y%m%d%H%M%S")
        return {
            "device_id": device_id,
            "timestamp": timestamp_str,
            "datetime": dt,
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H%M%S"),
            "media_num": media_num,
            "ext": ext.lower(),
            "key": key,
        }

    def get_device_ids(self) -> list[str]:
        """Return list of known device IDs."""
        if not self.data:
            return []
        return list(self.data.get("devices", {}).keys())

    def get_device_data(self, device_id: str) -> dict[str, Any] | None:
        """Return data for a specific device."""
        if not self.data:
            return None
        return self.data.get("devices", {}).get(device_id)

    def get_media_root(self) -> Path:
        """Return the media root directory."""
        return self._media_root
