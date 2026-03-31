"""Constants for the GardePro Trail Camera integration."""
from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "gardepro"

# GardePro cloud API
API_BASE: Final = "https://us.api.zopudt.com/api"
API_HEADERS: Final = {
    "Content-Type": "application/json; charset=UTF-8",
    "source": "Web",
    "platType": "Chrome",
    "platVer": "146.0",
    "appBrand": "GardePro WEB",
    "appVer": "1.0.0",
    "Time-Zone": "America/Los_Angeles",
    "app_userid": "0",
}

# S3 configuration
S3_BUCKET: Final = "trailcamera-media"
S3_REGION: Final = "us-west-2"

# Token lifetimes (conservative margins)
API_TOKEN_LIFETIME: Final = timedelta(days=6)  # actual: 7 days
S3_TOKEN_LIFETIME: Final = timedelta(hours=7)  # actual: ~12 hours

# Polling intervals
SCAN_INTERVAL_MEDIA: Final = timedelta(seconds=30)
SCAN_INTERVAL_TELEMETRY: Final = timedelta(minutes=5)

# Config flow
CONF_EMAIL: Final = "email"
CONF_PASSWORD: Final = "password"

# Media storage
MEDIA_DIR: Final = "trailcam"

# Camera name overrides: simDeviceId -> friendly directory name.
# Used when the cloud API returns an empty device name.
CAMERA_NAMES: Final = {
    "9135": "driveway",
}

# S3 key regex pattern: {simDeviceId}/{YYYYMMDDHHMMSS}/thumb{N}[_extra].JPG|MP4
S3_KEY_PATTERN: Final = r"^(\d+)/(\d{14})/thumb(\d+)(?:_\d+_-?\d+)?\.(JPG|MP4)$"
