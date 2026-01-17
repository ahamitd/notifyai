# AI Notification Generator for Home Assistant

<img src="images/logo.png" width="150" align="right" alt="Logo"> (Pro Edition)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

A professional-grade AI notification system for Home Assistant. It transforms standard automation alerts into intelligent, human-like, and **visually aware** notifications.

## 🌟 Pro Features
- **📸 Visual Intelligence (Vision)**: Send an image, and the AI will describe what it sees ("A courier with a package") instead of generic text.
- **🎭 Personas**: Define a character (e.g., `persona: "Jarvis"`). The AI will adopt this personality completely.
- **📡 Multi-Device Sync**: Configure up to 4 devices in Settings. The AI will automatically blast the notification to all of them.
- **🧠 Smart Context**: Analyzes multiple data points to generate relevant content.

## Installation

1. **HACS**: Add this repo > Install "**AI Notification Generator**".
2. **Restart Home Assistant**.

## Configuration

1. Go to **Settings > Devices & Services**.
2. Add Integration > **AI Notification Generator**.
3. Enter your **Google Gemini API Key** (starts with `AIza...`).
   - Get your free API key at: [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
   - **Note**: This integration uses the Gemini API already installed by Home Assistant's official Gemini integration, so no additional dependencies are needed.

### 🔧 Global Settings (Important)
Click **Configure** on the integration card to set:
- **AI Model**: e.g., `gemini-flash-latest`.
- **Notification Service 1-4**: Enter your device services here (e.g., `notify.mobile_app_iphone`, `notify.salon_tv`).
  *If you set these, you don't need to specify `notify_service` in your automations anymore!*

## Usage

### 1. Zero-Config (Using Global Settings)
If you configured your devices in Settings, just call this:

```yaml
service: ai_notification.generate
data:
  event: "Front door opened"
  time: "{{ now().strftime('%H:%M') }}"
  context: "Home armed"
  mode: "smart"
```
*Result: Sent to all configured devices automatically.*

### 2. Visual Analysis 📸
```yaml
service: ai_notification.generate
data:
  event: "Person at the door"
  time: "{{ now().strftime('%H:%M') }}"
  image_path: "/config/www/doorbell_snapshot.jpg" 
```

### 3. Custom Persona 🎭
```yaml
service: ai_notification.generate
data:
  event: "Vacuum finished"
  time: "{{ now().strftime('%H:%M') }}"
  persona: "Sarcastic Robot"
```

### 4. Single-Device Override
If you want to send ONLY to a specific device (ignoring global settings):

```yaml
service: ai_notification.generate
data:
  event: "Test message"
  time: "10:00"
  notify_service: "notify.mobile_app_tablet" # Overrides global settings
```
