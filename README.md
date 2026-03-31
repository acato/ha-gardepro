# GardePro Trail Camera for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration for GardePro cellular trail cameras. Polls the GardePro cloud API for device telemetry and new media captures, downloading images locally for use in automations and dashboards.

## Features

- **Automatic camera discovery** from your GardePro account
- **Real-time media sync** -- polls the notification feed every 30 seconds for new captures
- **Full device telemetry** -- battery, SD card usage, signal strength, temperature, photo/video counts, firmware version, plan days remaining
- **Camera entity** -- shows the latest capture as a camera entity in HA
- **Event firing** -- fires `gardepro_new_capture` events for use in automations
- **Token lifecycle management** -- handles API token (7-day TTL) and S3 federation token (8-hour TTL) refresh automatically

## Entities

Each physical camera is registered as an HA device with these entities:

| Entity | Type | Description |
|--------|------|-------------|
| Battery | Sensor | Battery level (%) |
| SD Used | Sensor | SD card used space (GB) |
| SD Usage | Sensor | SD card used (%) |
| Signal | Sensor | Cellular signal strength (bars) |
| Temperature | Sensor | Device temperature (C) |
| Photos | Sensor | Total photo count |
| Videos | Sensor | Total video count |
| Plan Days Left | Sensor | Days remaining on cloud plan |
| Firmware | Sensor | Current firmware version |
| Last Activity | Sensor | Timestamp of last activity |
| Online | Binary Sensor | Camera connectivity status |
| Latest Capture | Camera | Most recent image |

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Click the three-dot menu and select **Custom repositories**
3. Add `https://github.com/acato/ha-gardepro` with category **Integration**
4. Search for "GardePro" and install
5. Restart Home Assistant
6. Go to **Settings > Devices & Services > Add Integration > GardePro Trail Camera**

### Manual

1. Copy `custom_components/gardepro/` to your HA `config/custom_components/` directory
2. Restart Home Assistant
3. Go to **Settings > Devices & Services > Add Integration > GardePro Trail Camera**

## Configuration

The integration is configured through the UI. You will need your GardePro cloud account email and password (the same credentials you use in the GardePro mobile app or web interface).

## Media Storage

Downloaded images are stored in:
```
/media/gardepro/{camera_name}/{YYYY-MM-DD}/{HHMMSS}_{N}.jpg
/media/gardepro/{camera_name}/latest.jpg
```

The `latest.jpg` symlink is updated with each new capture, making it easy to reference in dashboards and notifications.

## Automation Examples

### Notification on new capture

```yaml
automation:
  - alias: "Trail Cam: New Capture Notification"
    trigger:
      - trigger: event
        event_type: gardepro_new_capture
    action:
      - action: notify.mobile_app_your_phone
        data:
          title: "Trail Cam: {{ trigger.event.data.camera_name | title }}"
          message: "New capture at {{ now().strftime('%H:%M') }}"
          data:
            image: "/api/camera_proxy/camera.gardepro_{{ trigger.event.data.camera_name }}_latest_capture"
```

### Low battery alert

```yaml
automation:
  - alias: "Trail Cam: Low Battery"
    trigger:
      - trigger: numeric_state
        entity_id: sensor.gardepro_driveway_battery
        below: 20
    action:
      - action: notify.mobile_app_your_phone
        data:
          title: "Trail Cam Battery Low"
          message: "Driveway camera is at {{ states('sensor.gardepro_driveway_battery') }}%"
```

## How It Works

The integration uses the GardePro cloud API (the same backend used by the GardePro web app):

1. **Authentication**: Logs in with email/password to obtain an API token (7-day TTL)
2. **Device discovery**: Fetches the device list to create HA devices
3. **Notification polling**: Every 30 seconds, checks the notification feed for new media
4. **Media download**: Uses S3 federation tokens (8-hour TTL) to download images from AWS S3
5. **Telemetry refresh**: Every ~5 minutes, refreshes full device status (battery, signal, etc.)

## Requirements

- A GardePro cellular trail camera with an active cloud plan
- GardePro cloud account (email + password)
- Home Assistant 2024.1.0 or newer

## License

MIT
