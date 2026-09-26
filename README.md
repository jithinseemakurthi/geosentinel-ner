# GeoSentinel-NER

AI-Powered Landslide Early Warning & Monitoring Platform for North Eastern Region, India.

GeoSentinel ingests weather (Open-Meteo / IMD), satellite, IoT-sensor and citizen-report
data, computes landslide risk, and issues multi-channel alerts (SMS via mock/TextBelt/
MSG91/Twilio/Textbee, push, WhatsApp, CAP/SACHET) with a real-time GIS dashboard.

## Architecture

```
geosentinel-ner/
├── docker-compose.yml          # Local development stack
├── .env.example                # Environment variables template
├── Makefile                    # Common commands
├── docs/                       # API contract
├── infra/monitoring/           # Prometheus scrape config
├── packages/
│   └── geosentinel-shared/     # Shared config/auth/db/logging/schemas/districts
├── services/
│   ├── api-gateway/            # FastAPI gateway: auth, RBAC, rate limiting, WebSocket
│   ├── data-ingestion/         # Open-Meteo, IMD WFS, satellite, IoT collectors
│   ├── ml-engine/              # M1/M2/M3 inference (heuristic fallback until trained)
│   ├── alert-engine/           # Rule engine, alert persistence, dispatch bookkeeping
│   ├── gis-service/            # PostGIS spatial queries (+ TiTiler for rasters)
│   ├── report-service/         # Citizen reports, CV triage endpoint
│   ├── notification-service/   # Multi-channel delivery + NE-states SMS digest
│   └── textbelt/               # Vendored open-source SMS gateway (Node)
├── apps/
│   └── web-dashboard/          # React + MapLibre GL PWA (Vite)
├── data/
│   ├── schemas/migrations/     # SQL migrations (auto-applied on first postgres init)
│   ├── seeds/                  # Reference data
│   └── samples/                # Sample GeoJSON / CSVs for dev
├── scripts/                    # Admin password reset, live weather demo feed
└── tests/                      # Root pytest suite (shared package + services)
```

## Quick Start

```bash
# 1. Copy env template and fill in secrets
cp .env.example .env

# 2. Start local stack (PostGIS, TimescaleDB, Redis, MinIO; optional Kafka/GeoServer)
docker compose up -d

# 3. Run database migrations + seed reference data
make migrate
make seed

# 4. Open the dashboard
#    http://localhost:3000  (web)   http://localhost:8000/docs (gateway, APP_DEBUG=true)
```

### Running tests locally

```bash
# Python (root suite — shared package + service logic)
uv venv .venv --python 3.11
uv pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest        # Windows
.venv/bin/python -m pytest            # Linux/macOS

# Frontend
cd apps/web-dashboard && npm install
npm run test:unit                     # vitest
npm run typecheck && npm run lint
```

Or simply `make test` / `make lint` once `.venv` exists.

## Services

| Service | Port | Description |
|---------|------|-------------|
| api-gateway | 8000 | Auth, routing, rate limiting, WebSocket fan-out |
| data-ingestion | 8001 | External API collectors (Open-Meteo, IMD, Sentinel) |
| ml-engine | 8002 | Model inference (REST + async) |
| alert-engine | 8003 | Rule evaluation, cooldowns, alert persistence |
| gis-service | 8004 | Vector tiles, spatial queries |
| report-service | 8005 | Citizen reports, CV triage |
| notification-service | 8006 | SMS, Push, Email, WhatsApp, CAP |
| textbelt | 9090 | Self-hosted SMS gateway (optional) |
| web-dashboard | 3000 | React PWA dashboard |

All ports are bound to `127.0.0.1` only. Internal services trust the gateway;
never expose them directly to a LAN.

## Environment Variables

Key variables (see `.env.example`):

- `DATABASE_URL` - PostgreSQL + PostGIS connection
- `TIMESCALE_URL` - TimescaleDB for sensor time-series
- `REDIS_URL` - Cache, rate limiting
- `MINIO_ENDPOINT` - S3-compatible storage
- `IMD_API_KEY` - IMD weather API
- `SENTINEL_HUB_KEY` - Copernicus/Sentinel Hub
- `SMS_PROVIDER` - `mock` for a safe demo, or `textbelt`/MSG91/Twilio/Textbee for live delivery
- `TEXTBELT_URL` - TextBelt endpoint, normally `http://localhost:9090/intl`
- `ALERT_RECIPIENT_PHONES` - comma-separated E.164 SMS recipients (for example `+919876543210`)
- `SMS_TEMPLATE_ID_ALERT` - approved MSG91 DLT template used by rainfall alerts
- `CAP_ENDPOINT` - NDMA SACHET/CAP endpoint

### SMS demo mode (no API key required)

Set `SMS_PROVIDER=mock` to demonstrate the complete SMS workflow without an
SMS account. The API returns a simulated provider message ID and the service
logs the delivery; it does **not** send a text to a real phone. This is the
safe default for student demonstrations. Use `textbelt`, `msg91`, or `twilio`
only when you have configured a real provider.

### Rainfall SMS alerts

The notification service exposes an admin-only `POST /api/v1/alerts/rainfall`
endpoint. It sends SMS to `ALERT_RECIPIENT_PHONES` when observed rainfall,
forecast rainfall, landslide probability, or reported excavation activity
crosses the configured thresholds. Configure `SMS_API_KEY`, an approved
`SMS_TEMPLATE_ID_ALERT` when using MSG91, or configure TextBelt as described
below, plus the recipient number; no message is sent when no threshold is
crossed.

For self-hosted TextBelt delivery, GeoSentinel includes the upstream TextBelt
service under `services/textbelt`. Configure Gmail with an **App Password**
(never your normal Gmail password):

```bash
TEXTBELT_SMTP_USER=yourgmailaddress@gmail.com
TEXTBELT_SMTP_PASS=<16-character Gmail App Password>
TEXTBELT_FROM_NAME=GeoSentinel
TEXTBELT_FROM_ADDRESS=yourgmailaddress@gmail.com
ALERT_RECIPIENT_PHONES=+919876543210
```

Start it with `docker compose up -d textbelt notification-service`, or run
TextBelt locally with `cd services/textbelt && npm install && npm start`.

Example request:

```bash
curl -X POST http://localhost:8006/api/v1/alerts/rainfall \
  -H "Authorization: Bearer <admin-access-token>" \
  -H "Content-Type: application/json" \
  -d '{"location":"Aizawl Ridge","observed_rainfall_mm":62,"forecast_rainfall_mm":80,"landslide_probability":0.78,"excavation_active":true}'
```

### 30-minute North East SMS digest

Set the following in `.env` after configuring an SMS provider. The digest is
off by default, so no recurring messages are sent until you enable it.

```bash
NORTHEAST_DIGEST_ENABLED=true
NORTHEAST_DIGEST_INTERVAL_MINUTES=30
NORTHEAST_DIGEST_RECIPIENT_PHONES=+919876543210
NORTHEAST_DIGEST_MAX_LENGTH=640
```

Every run sends a compact situation report for Arunachal Pradesh, Assam,
Manipur, Meghalaya, Mizoram, Nagaland, Sikkim, and Tripura. It includes a
representative state location's observed rainfall (last 24 hours), forecast
rainfall (next 24 hours), temperature, and an elevated-rainfall watch.
`NORTHEAST_DIGEST_RECIPIENT_PHONES` falls back to `ALERT_RECIPIENT_PHONES` if
left blank. The scheduler uses India Standard Time and starts with the
notification service.

To test one digest immediately, use an admin access token:

```bash
curl -X POST http://localhost:8006/api/v1/digests/northeast/send \
  -H "Authorization: Bearer <admin-access-token>"
```

Use `GET /api/v1/digests/northeast/status` with the same token to check the
last delivery result and whether the scheduler is active.

When using a free Twilio trial, Twilio permits only its predefined message
templates and verified recipient numbers. Set
`TWILIO_TRIAL_TEMPLATE=sms_account_alerts` to test scheduled delivery. The
actual weather digest requires a paid Twilio account, where
`TWILIO_TRIAL_TEMPLATE` must be left blank.

### Free alert channels — no SMS provider or Android phone needed

GeoSentinel can deliver every rainfall alert and the 30-minute NE digest
through **free** channels alongside (or instead of) SMS:

| Channel | Setup | Recipient needs |
|---------|-------|-----------------|
| WhatsApp (CallMeBot) | From the recipient phone's WhatsApp, send `I allow callmebot to send me messages` to **+34 644 66 32 62**, then copy the API key it replies with into `CALLMEBOT_API_KEY` | Nothing further |
| Telegram | Create a bot with [@BotFather](https://t.me/BotFather), set `TELEGRAM_BOT_TOKEN`; recipients press Start on your bot and their chat IDs go in `TELEGRAM_CHAT_IDS` | Telegram app |
| Push (ntfy.sh) | Install the [ntfy app](https://ntfy.sh), subscribe to a random private topic (e.g. `geo-alerts-x7f3k9`), list topics in `NTFY_TOPICS` | ntfy app |

Enable them with one variable:

```bash
ALERT_FREE_CHANNELS=whatsapp,telegram,push
```

Every rainfall alert (`POST /api/v1/alerts/rainfall`) and scheduled digest is
then fanned out across all enabled channels automatically — one failing
channel never blocks the others. Verify with an admin token:

```bash
# Which channels are enabled/configured?
curl http://localhost:8006/api/v1/free-channels -H "Authorization: Bearer <admin-token>"

# Send one test message through all enabled channels
curl -X POST http://localhost:8006/api/v1/test/free-channels -H "Authorization: Bearer <admin-token>"
```

These channels are free for personal use; for public-scale deployments use a
proper SMS provider (MSG91 DLT templates etc.) as the primary channel.

### Real weather SMS without a paid API: your Android phone

[Textbee](https://github.com/textbee/textbee) sends real SMS through your own
Android phone and SIM. Install its Android app, grant SMS permission,
register the device, and generate its API key. Then set:

```bash
SMS_PROVIDER=textbee
TEXTBEE_API_KEY=<key from textbee dashboard>
```

Keep the phone powered, connected to the internet, and with an active SMS plan.
If delivery fails, GeoSentinel now surfaces textbee's HTTP response verbatim in
the error/logs (e.g. device offline or unregistered), so setup problems are
easy to spot. Your mobile carrier's normal SMS terms still apply.

## ML pipeline status

Training and feature-engineering prototypes for M1/M2/M3 live under
`ml/training` and `ml/features`. The inference API loads registered model
artifacts when available and otherwise uses transparent heuristic fallbacks:

- **M1 Susceptibility**: XGBoost on terrain + geology + historical inventory → static risk zones
- **M2 Dynamic Risk**: Gradient Boosting + LSTM on rainfall forecast + soil moisture + antecedent indices → 24/48/72h probability
- **M3 Report Triage**: MobileNetV3 / EfficientNet on citizen photos → crack/bulge/debris classification

The automated training tests currently use synthetic datasets. Validation on
labeled regional data and publishing validated artifacts to the model registry
remain roadmap work; heuristic output should be treated as a prototype signal.

## Roadmap

- Flutter offline-first mobile app (`apps/mobile-app`)
- Regional dataset validation + MLflow model registry population
- Terraform / Kubernetes manifests for staging & production
- Kafka event backbone (compose profile already wired)

## Deployment

- **Development**: `docker-compose.yml`
- **CI/CD**: GitHub Actions — ruff + pytest, frontend build/test, compose validation

## License

MIT — see [LICENSE](LICENSE).
