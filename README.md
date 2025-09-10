# Envertech Local Integration for Home Assistant
A custom integration for Home Assistant that enables monitoring and control of Envertech micro inverters locally, without relying on cloud services.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Kaiserdragon2&repository=Envertech_local&category=integration)

## Description
This integration allows you to connect your Envertech solar micro inverters to Home Assistant for local monitoring of power generation, voltage, current and other metrics directly from your inverters.

## Features
- Local communication with Envertech inverters
- No cloud dependency required

## Installation

### 🧰 Via HACS (recommended)
1. In HACS, go to **Integrations** → three dots menu → **Custom repositories**.
2. Add this repository:  
   `https://github.com/Kaiserdragon2/Envertech_local`
3. Search for **Envertech Local** in HACS and install.
4. Restart Home Assistant.
5. Go to **Settings → Devices & Services → + Add Integration**, search for "Envertech".
6. Follow the config flow.

### 🛠️ Manual Installation
1. Download or clone this repository.
2. Copy the folder `envertech_local` to:  
   `custom_components/envertech_local/` inside your Home Assistant config directory.
3. Restart Home Assistant and follow the same setup as above.

## Configuration
[Configuration details will be added]

## Supported Devices
[List of compatible Envertech inverter models will be added]

## Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

## License
[License information will be added]

## Disclaimer
This is a third-party integration and is not officially supported by Envertech.
*Home Assistant integration for Envertech micro inverter*