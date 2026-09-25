# GeoSentinel-NER Mobile Application

Offline-first Flutter mobile application for field disaster officers and citizens in the North Eastern Region of India.

## Features

- **Offline-first Architecture**: Uses local SQLite storage to cache landslide risk zones, alerts, evacuation shelters, and offline report queues.
- **Bi-directional Sync Engine**: Auto-syncs queued incident reports with media uploads when internet connectivity (2G/3G/4G/WiFi) is restored.
- **Multi-lingual Support**: Full localization for 8 North Eastern languages (English, Hindi, Assamese, Bengali, Mizo, Khasi, Manipuri, Nepali).
- **Interactive Offline Hazard Map**: Vector & raster tile caching for remote mountain regions without cell towers.
- **One-touch SOS & Citizen Reporting**: Rapid landslide reporting with GPS auto-capture and offline photo queuing.
- **Emergency Push & SMS Broadcasts**: Multi-channel emergency alerting with priority sound and local vibration alarms.

## Architecture

```
lib/
├── main.dart
├── core/
│   ├── config/app_config.dart
│   ├── database/database_helper.dart
│   ├── network/api_client.dart
│   ├── sync/sync_manager.dart
│   ├── theme/app_theme.dart
│   └── i18n/app_translations.dart
├── models/
│   ├── alert_model.dart
│   ├── citizen_report_model.dart
│   └── risk_zone_model.dart
├── services/
│   ├── alert_service.dart
│   ├── report_service.dart
│   ├── location_service.dart
│   └── notification_service.dart
└── ui/
    ├── screens/
    │   ├── home_screen.dart
    │   ├── map_screen.dart
    │   ├── alerts_screen.dart
    │   ├── report_screen.dart
    │   ├── shelters_screen.dart
    │   └── settings_screen.dart
    └── widgets/
        ├── risk_badge.dart
        ├── offline_banner.dart
        └── sos_button.dart
```

## Running the App

```bash
flutter pub get
flutter run
```
