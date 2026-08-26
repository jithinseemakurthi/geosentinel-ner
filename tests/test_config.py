"""Tests for geosentinel_shared.config (Settings validation)."""
import pytest
from pydantic import ValidationError

from geosentinel_shared import config

VALID = {
    "SECRET_KEY": "x" * 48,
    "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
    "TIMESCALE_URL": "postgresql://u:p@localhost:5433/ts",
}


def make_settings(**overrides):
    # _env_file=None isolates each instance from any on-disk .env file.
    return config.Settings(_env_file=None, **{**VALID, **overrides})


class TestBasicSettings:
    def test_minimal_valid_settings(self):
        s = make_settings()
        assert s.APP_ENV == "development"
        assert not s.is_production

    def test_missing_secret_key_rejected(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with pytest.raises(ValidationError):
            config.Settings(
                _env_file=None,
                DATABASE_URL=VALID["DATABASE_URL"],
                TIMESCALE_URL=VALID["TIMESCALE_URL"],
            )

    def test_short_secret_key_rejected(self):
        with pytest.raises(ValidationError):
            make_settings(SECRET_KEY="too-short")

    def test_placeholder_style_secret_with_whitespace_rejected(self):
        with pytest.raises(ValidationError):
            make_settings(SECRET_KEY="python -c import secrets print secrets")

    @pytest.mark.parametrize("env", ["dev", "prod", "PRODUCTION ", "staging1"])
    def test_invalid_app_env_rejected(self, env):
        with pytest.raises(ValidationError):
            make_settings(APP_ENV=env)

    @pytest.mark.parametrize("level", ["debug", "INFO", "warning", "ERROR"])
    def test_log_level_normalised(self, level):
        assert make_settings(LOG_LEVEL=level).LOG_LEVEL == level.upper()

    def test_invalid_log_level_rejected(self):
        with pytest.raises(ValidationError):
            make_settings(LOG_LEVEL="verbose")


class TestProductionHardening:
    def test_debug_in_production_rejected(self):
        with pytest.raises(ValidationError):
            make_settings(APP_ENV="production", APP_DEBUG=True)

    def test_wildcard_cors_in_production_rejected(self):
        with pytest.raises(ValidationError):
            make_settings(APP_ENV="production", CORS_ALLOW_ORIGINS="*")

    def test_default_minio_credentials_in_production_rejected(self):
        with pytest.raises(ValidationError):
            make_settings(APP_ENV="production", MINIO_ACCESS_KEY="minioadmin")

    def test_placeholder_secret_in_production_rejected(self):
        with pytest.raises(ValidationError):
            make_settings(APP_ENV="production", SECRET_KEY="REPLACE_WITH_a_real_key_0123456789")


class TestDerivedProperties:
    def test_csv_parsing(self):
        s = make_settings(CORS_ALLOW_ORIGINS="http://a.com, http://b.com ,,")
        assert s.cors_origins == ["http://a.com", "http://b.com"]

    def test_supported_languages(self):
        s = make_settings(SUPPORTED_LANGUAGES="en,hi,mn")
        assert s.supported_languages_list == ["en", "hi", "mn"]

    def test_allowed_hosts(self):
        s = make_settings(ALLOWED_HOSTS="localhost,example.gov.in")
        assert s.allowed_hosts == ["localhost", "example.gov.in"]


def test_get_settings_is_cached(monkeypatch):
    monkeypatch.setattr(config, "get_settings", config.lru_cache(config.get_settings.__wrapped__))
    a = config.get_settings()
    b = config.get_settings()
    assert a is b
