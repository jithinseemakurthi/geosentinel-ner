"""
GeoSentinel-NER Shared Configuration Module

Loads settings from .env file or environment variables. Refuses to start
in production with a weak or default SECRET_KEY.
"""
from functools import lru_cache
from typing import List, Optional

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Tokens that are clearly placeholders — reject these in production.
_INSECURE_SECRET_MARKERS = (
    "change-me",
    "changeme",
    "change_me",
    "replace-me",
    "replace_with",
    "your-secret",
    "your_secret",
    "yoursecret",
    "dummy",
    "placeholder",
    "insecure",
)
# Well-known default credentials that must never be used in production.
_INSECURE_DEFAULT_CREDENTIALS = {
    "",
    "geosentinel",
    "minioadmin",
    "admin",
    "password",
    "changeme",
    "change_me",
    "change-me",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Try .env in CWD; in containers the env vars are injected directly,
        # so this file is optional.
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ----- Application -----
    APP_ENV: str = Field(default="development", description="development|staging|production")
    APP_DEBUG: bool = Field(default=False, description="Debug mode — must be false in production")
    LOG_LEVEL: str = Field(default="INFO")
    SECRET_KEY: str = Field(..., description="HMAC key for JWT signing (≥32 chars in production)")
    API_PREFIX: str = Field(default="/api/v1")

    CORS_ALLOW_ORIGINS: str = Field(
        default="http://localhost:3000",
        description="Comma-separated list of allowed CORS origins",
    )
    ALLOWED_HOSTS: str = Field(
        default="localhost,127.0.0.1",
        description="Comma-separated list of allowed Host headers (TrustedHostMiddleware)",
    )

    # ----- Database -----
    DATABASE_URL: str = Field(...)
    TIMESCALE_URL: str = Field(...)

    # ----- Redis -----
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    REDIS_PASSWORD: Optional[str] = Field(default=None)

    # ----- MinIO / S3 -----
    MINIO_ENDPOINT: str = Field(default="localhost:9000")
    MINIO_ACCESS_KEY: str = Field(default="geosentinel")
    MINIO_SECRET_KEY: str = Field(default="geosentinel")
    MINIO_BUCKET: str = Field(default="geosentinel")
    MINIO_SECURE: bool = Field(default=False)

    # ----- Kafka -----
    KAFKA_BOOTSTRAP_SERVERS: str = Field(default="localhost:9092")
    KAFKA_CONSUMER_GROUP: str = Field(default="geosentinel")
    ENABLE_KAFKA: bool = Field(default=False)

    # ----- External APIs -----
    # Open-Meteo: keyless global weather forecast API (default rainfall provider)
    OPEN_METEO_BASE_URL: str = "https://api.open-meteo.com/v1"
    WEATHER_PROVIDER: str = "open-meteo"  # open-meteo | imd
    # TomTom (reverse geocoding, basemap tiles) — 2500 free calls/day
    # NOTE: keys are exactly 32 chars. Behind TLS-inspecting proxies set
    # SSL_CERT_FILE/REQUESTS_CA_BUNDLE to the proxy CA for local dev runs.
    TOMTOM_API_KEY: Optional[str] = None
    TOMTOM_BASE_URL: str = "https://api.tomtom.com"
    # Keyless fallback geocoder (OpenStreetMap Nominatim — heavy usage policy)
    NOMINATIM_BASE_URL: str = "https://nominatim.openstreetmap.org"
    IMD_API_KEY: Optional[str] = None
    IMD_API_BASE_URL: str = "https://api.imd.gov.in"
    SENTINEL_HUB_CLIENT_ID: Optional[str] = None
    SENTINEL_HUB_CLIENT_SECRET: Optional[str] = None
    SENTINEL_HUB_BASE_URL: str = "https://services.sentinel-hub.com"
    NRSC_API_KEY: Optional[str] = None
    NRSC_BASE_URL: str = "https://bhuvan.nrsc.gov.in/api"

    # ----- Alerting -----
    CAP_ENDPOINT: Optional[str] = None
    CAP_AUTH_TOKEN: Optional[str] = None
    # mock (safe local demo) | textbelt | msg91 | twilio | textbee
    SMS_PROVIDER: str = "mock"
    SMS_API_KEY: Optional[str] = None
    SMS_API_BASE_URL: str = "https://control.msg91.com/api/v5/flow"
    TEXTBELT_URL: str = "http://localhost:9090/intl"
    SMS_SENDER_ID: str = "GEONER"
    SMS_TEMPLATE_ID_ALERT: Optional[str] = None
    SMS_TEMPLATE_ID_OTP: Optional[str] = None
    ALERT_RECIPIENT_PHONES: str = ""
    ALERT_RAINFALL_THRESHOLD_MM: float = 50.0
    ALERT_FORECAST_RAINFALL_THRESHOLD_MM: float = 75.0
    ALERT_LANDSLIDE_PROBABILITY_THRESHOLD: float = 0.70
    # Periodic North East regional situation-report SMS digest.
    NORTHEAST_DIGEST_ENABLED: bool = False
    NORTHEAST_DIGEST_INTERVAL_MINUTES: int = Field(default=30, ge=5, le=1440)
    NORTHEAST_DIGEST_RECIPIENT_PHONES: str = ""
    NORTHEAST_DIGEST_MAX_LENGTH: int = Field(default=640, ge=160, le=1600)
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_FROM_NUMBER: Optional[str] = None
    # Free Twilio trials accept only one of Twilio's predefined SMS templates.
    # Leave empty for normal accounts, which send the application's message body.
    TWILIO_TRIAL_TEMPLATE: Optional[str] = None
    # Textbee sends via an Android phone/SIM and supports dynamic messages.
    TEXTBEE_API_URL: str = "https://api.textbee.dev/api/v1/gateway/send-sms"
    TEXTBEE_API_KEY: Optional[str] = None
    # ----- Free alert channels (no paid SMS provider required) -----
    # Comma-separated subset of: whatsapp, telegram, push.
    # Delivered alongside SMS on every rainfall alert / NE digest.
    ALERT_FREE_CHANNELS: str = ""
    # whatsapp: CallMeBot free API (one-time per-phone activation, see README)
    CALLMEBOT_API_URL: str = "https://api.callmebot.com/whatsapp.php"
    CALLMEBOT_API_KEY: Optional[str] = None
    # telegram: official Telegram Bot API (@BotFather token + chat IDs)
    TELEGRAM_API_URL: str = "https://api.telegram.org"
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_IDS: str = ""
    # push: ntfy.sh topics (install https://ntfy.sh app, subscribe to topic)
    NTFY_SERVER_URL: str = "https://ntfy.sh"
    NTFY_TOPICS: str = ""
    FIREBASE_PROJECT_ID: Optional[str] = None
    FIREBASE_PRIVATE_KEY: Optional[str] = None
    FIREBASE_CLIENT_EMAIL: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None

    # ----- ML -----
    MLFLOW_TRACKING_URI: str = "http://localhost:5000"
    MODEL_REGISTRY_URI: str = "s3://geosentinel/models"
    M1_MODEL_VERSION: str = "latest"
    M2_MODEL_VERSION: str = "latest"
    # Internal service discovery (override to http://data-ingestion:8001 in Docker)
    DATA_INGESTION_URL: str = "http://localhost:8001"
    M3_MODEL_VERSION: str = "latest"

    # ----- GIS -----
    # Host URL of the TiTiler tile server (compose maps it to host port 8104;
    # gis-service itself listens on 8004).
    TILE_SERVER_URL: str = "http://localhost:8104"
    TILE_CACHE_TTL: int = 3600

    # ----- Mobile -----
    MOBILE_API_BASE_URL: str = "http://localhost:8000/api/v1"
    MOBILE_OFFLINE_DB_NAME: str = "geosentinel_offline.db"

    # ----- i18n -----
    DEFAULT_LANGUAGE: str = "en"
    SUPPORTED_LANGUAGES: str = "en,hi,as,bn,bo,mni,lus,kha,grt,ne"

    # ----- Feature flags -----
    ENABLE_INSAR_PIPELINE: bool = False
    ENABLE_CV_TRIAGE: bool = True
    ENABLE_CAP_ALERTS: bool = False

    # ----- Limits & security -----
    MAX_UPLOAD_BYTES: int = Field(default=25 * 1024 * 1024)
    RATE_LIMIT_PER_MINUTE: int = 60
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Only set to True when running behind a trusted reverse proxy that sets
    # X-Forwarded-For. When False (default), client IP comes from the socket,
    # so rate limiting cannot be bypassed by spoofing headers.
    TRUST_PROXY_HEADERS: bool = Field(
        default=False,
        description="Trust X-Forwarded-For for client IP detection (only behind a trusted proxy)",
    )

    # ----- Validators -----
    @field_validator("APP_ENV")
    @classmethod
    def _normalise_env(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"development", "staging", "production", "test"}:
            raise ValueError(f"APP_ENV must be one of development|staging|production|test, got {v!r}")
        return v

    @field_validator("SECRET_KEY")
    @classmethod
    def _check_secret_key(cls, v: str, info: ValidationInfo) -> str:
        if v is None or len(v) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters. "
                "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(64))'"
            )
        # Catch verbatim copies of the .env.example template (contains shell
        # substitution backticks / whitespace — never a valid key).
        if "`" in v or any(c.isspace() for c in v):
            raise ValueError(
                "SECRET_KEY looks like an unedited .env.example placeholder "
                "(contains backticks or whitespace). Generate a real key with: "
                "python -c 'import secrets; print(secrets.token_urlsafe(64))'"
            )
        env = (info.data.get("APP_ENV") or "").lower()
        if env in {"production", "staging"}:
            lowered = v.lower()
            for marker in _INSECURE_SECRET_MARKERS:
                if marker in lowered:
                    raise ValueError(
                        f"SECRET_KEY contains insecure placeholder text ({marker!r}). "
                        "Generate a strong key with: "
                        "python -c 'import secrets; print(secrets.token_urlsafe(64))'"
                    )
        return v

    @model_validator(mode="after")
    def _check_production_hardening(self) -> "Settings":
        """Enforce the 'refuses to start insecure in production' promise."""
        if not self.is_production:
            return self
        if self.APP_DEBUG:
            raise ValueError("APP_DEBUG must be false in production")
        if "*" in self.cors_origins:
            raise ValueError("CORS_ALLOW_ORIGINS must not contain '*' in production")
        if "*" in self.allowed_hosts:
            raise ValueError("ALLOWED_HOSTS must not contain '*' in production")
        if self.MINIO_ACCESS_KEY.strip().lower() in _INSECURE_DEFAULT_CREDENTIALS or \
                self.MINIO_SECRET_KEY.strip().lower() in _INSECURE_DEFAULT_CREDENTIALS:
            raise ValueError(
                "MINIO_ACCESS_KEY/MINIO_SECRET_KEY must be changed from well-known "
                "defaults before running in production"
            )
        return self

    # NOTE: CORS_ALLOW_ORIGINS / ALLOWED_HOSTS / SUPPORTED_LANGUAGES stay as
    # raw CSV strings. Do NOT add a mode="before" splitter here — it would
    # produce a list that fails str validation and crash every service at
    # startup. Use the derived properties (cors_origins, allowed_hosts,
    # supported_languages_list) which parse the CSV safely.

    @field_validator("LOG_LEVEL")
    @classmethod
    def _check_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Invalid LOG_LEVEL: {v}")
        return v

    # ----- Derived properties -----
    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def cors_origins(self) -> List[str]:
        v = self.CORS_ALLOW_ORIGINS
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def allowed_hosts(self) -> List[str]:
        v = self.ALLOWED_HOSTS
        if isinstance(v, str):
            return [h.strip() for h in v.split(",") if h.strip()]
        return v

    @property
    def supported_languages_list(self) -> List[str]:
        v = self.SUPPORTED_LANGUAGES
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    # We don't fail on missing .env in containers — env vars are passed via env_file.
    # pydantic-settings will fall back to os.environ when .env is absent.
    return Settings()  # type: ignore[call-arg]


def __getattr__(name: str):
    """Lazy module-level `settings` (PEP 562).

    Importing this module no longer requires env vars to be present —
    Settings() is instantiated on first ACCESS. This keeps tests, Alembic,
    and tooling importable without a full environment while runtime
    behaviour is unchanged.
    """
    if name == "settings":
        cached = get_settings()
        globals()["settings"] = cached
        return cached
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
