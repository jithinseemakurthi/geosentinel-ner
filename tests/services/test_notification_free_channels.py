"""Tests for the free alert-channel dispatchers in notification-service."""
from uuid import uuid4

import httpx
import pytest
from conftest import load_service_module

notification = load_service_module(
    "notification_free", "services/notification-service/app/main.py"
)
FreeChannelDispatcher = notification.FreeChannelDispatcher


# -----------------------------------------------------------------------------
# httpx stubbing
# -----------------------------------------------------------------------------
class StubResponse:
    def __init__(self, status_code=200, text="", json_body=None):
        self.status_code = status_code
        self.text = text
        self._json = json_body

    def json(self):
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json


class RecordingAsyncClient:
    """Stands in for httpx.AsyncClient and records every request made."""

    calls = []
    responses = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, params=None, **kwargs):
        type(self).calls.append({"method": "GET", "url": url, "params": params, **kwargs})
        return type(self).responses.pop(0)

    async def post(self, url, params=None, **kwargs):
        type(self).calls.append({"method": "POST", "url": url, "params": params, **kwargs})
        return type(self).responses.pop(0)


@pytest.fixture()
def stub_http(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", RecordingAsyncClient)
    RecordingAsyncClient.calls = []
    RecordingAsyncClient.responses = []
    return RecordingAsyncClient


@pytest.fixture()
def free_settings(monkeypatch):
    """Point every free channel at fake credentials."""
    monkeypatch.setattr(notification.settings, "ALERT_FREE_CHANNELS", "")
    monkeypatch.setattr(notification.settings, "CALLMEBOT_API_KEY", "cmb-key-123")
    monkeypatch.setattr(notification.settings, "TELEGRAM_BOT_TOKEN", "tg-token-456")
    monkeypatch.setattr(notification.settings, "TELEGRAM_CHAT_IDS", "111,222")
    monkeypatch.setattr(notification.settings, "NTFY_TOPICS", "geo-alerts-x7f3")
    monkeypatch.setattr(notification.settings, "ALERT_RECIPIENT_PHONES", "+919876543210")


class TestChannelParsing:
    def test_empty_config_disables_everything(self):
        assert FreeChannelDispatcher().active == []

    def test_known_channels_parsed(self, monkeypatch):
        monkeypatch.setattr(
            notification.settings, "ALERT_FREE_CHANNELS", "whatsapp, push"
        )
        d = FreeChannelDispatcher()
        assert d.active == ["whatsapp", "push"]  # canonical order
        assert d.unknown_channels == []

    def test_unknown_channels_reported(self, monkeypatch):
        monkeypatch.setattr(
            notification.settings, "ALERT_FREE_CHANNELS", "sms-by-carrier-pigeon,push"
        )
        d = FreeChannelDispatcher()
        assert d.active == ["push"]
        assert d.unknown_channels == ["sms-by-carrier-pigeon"]


class TestWhatsAppCallMeBot:
    async def test_success_posts_get_with_params(self, stub_http, free_settings):
        stub_http.responses.append(StubResponse(text="Message Queued"))
        d = FreeChannelDispatcher()  # reads patched settings
        result = await d.send_whatsapp("+919876543210", "Rain alert!")
        assert result["status"] == "sent"
        assert result["channel"] == "whatsapp"
        call = stub_http.calls[0]
        assert call["url"].endswith("whatsapp.php")
        assert call["params"]["apikey"] == "cmb-key-123"
        assert call["params"]["phone"] == "+919876543210"

    async def test_missing_api_key_raises(self, stub_http, free_settings, monkeypatch):
        monkeypatch.setattr(notification.settings, "CALLMEBOT_API_KEY", None)
        with pytest.raises(RuntimeError, match="CALLMEBOT_API_KEY"):
            await FreeChannelDispatcher().send_whatsapp("+919876543210", "hi")

    async def test_rejection_text_raises(self, stub_http, free_settings):
        stub_http.responses.append(StubResponse(status_code=200, text="Message NOT Sent to your number"))
        with pytest.raises(RuntimeError, match="CallMeBot rejected"):
            await FreeChannelDispatcher().send_whatsapp("+919876543210", "hi")

    async def test_bad_phone_rejected(self, stub_http, free_settings):
        with pytest.raises(ValueError, match="E.164"):
            await FreeChannelDispatcher().send_whatsapp("9876543210", "hi")


class TestTelegram:
    async def test_success_returns_message_id(self, stub_http, free_settings):
        stub_http.responses.append(StubResponse(json_body={"ok": True, "result": {"message_id": 42}}))
        result = await FreeChannelDispatcher().send_telegram("111", "digest text")
        assert result["status"] == "sent"
        assert result["provider_message_id"] == "42"
        call = stub_http.calls[0]
        assert "/bottg-token-456/sendMessage" in call["url"]
        assert call["json"]["chat_id"] == "111"

    async def test_unauthorized_token_raises(self, stub_http, free_settings):
        stub_http.responses.append(StubResponse(status_code=401, json_body={"ok": False}))
        with pytest.raises(RuntimeError, match="Telegram rejected"):
            await FreeChannelDispatcher().send_telegram("111", "x")

    async def test_missing_token_raises(self, stub_http, free_settings, monkeypatch):
        monkeypatch.setattr(notification.settings, "TELEGRAM_BOT_TOKEN", None)
        with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
            await FreeChannelDispatcher().send_telegram("111", "x")

    async def test_blank_chat_id_rejected(self, stub_http, free_settings):
        with pytest.raises(ValueError, match="chat id"):
            await FreeChannelDispatcher().send_telegram("  ", "x")


class TestPushNtfy:
    async def test_success_posts_to_topic(self, stub_http, free_settings):
        stub_http.responses.append(StubResponse())
        result = await FreeChannelDispatcher().send_push("geo-alerts-x7f3", "body", title="T")
        assert result["channel"] == "push"
        call = stub_http.calls[0]
        assert call["url"].endswith("/geo-alerts-x7f3")
        assert call["headers"]["Title"] == "T"

    async def test_invalid_topic_rejected(self, stub_http, free_settings):
        with pytest.raises(ValueError, match="topic"):
            await FreeChannelDispatcher().send_push("../etc-passwd", "body")


class TestFanOut:
    async def test_all_enabled_channels_deliver(self, stub_http, free_settings, monkeypatch):
        monkeypatch.setattr(
            notification.settings, "ALERT_FREE_CHANNELS", "whatsapp,telegram,push"
        )
        stub_http.responses.extend([
            StubResponse(text="ok"),                                    # whatsapp
            StubResponse(json_body={"ok": True, "result": {"message_id": 1}}),  # tg 111
            StubResponse(json_body={"ok": True, "result": {"message_id": 2}}),  # tg 222
            StubResponse(),                                             # ntfy
        ])
        results = await notification.deliver_via_free_channels("msg", title="t")
        statuses = [r["status"] for r in results]
        assert statuses == ["sent", "sent", "sent", "sent"]
        recipients = [r["recipient"] for r in results]
        assert any("@telegram" in r for r in recipients)
        assert any("@push" in r for r in recipients)

    async def test_one_channel_failure_does_not_block_others(self, stub_http, free_settings, monkeypatch):
        monkeypatch.setattr(
            notification.settings, "ALERT_FREE_CHANNELS", "whatsapp,push"
        )
        stub_http.responses.extend([
            StubResponse(status_code=500, text="boom"),  # whatsapp fails
            StubResponse(),                              # push succeeds
        ])
        results = await notification.deliver_via_free_channels("msg")
        by_channel = {r["recipient"].split("@")[1]: r["status"] for r in results}
        assert by_channel == {"whatsapp": "failed", "push": "sent"}

    async def test_no_recipients_reports_failure_without_raising(self, stub_http, free_settings, monkeypatch):
        monkeypatch.setattr(notification.settings, "ALERT_FREE_CHANNELS", "whatsapp")
        monkeypatch.setattr(notification.settings, "ALERT_RECIPIENT_PHONES", "")
        results = await notification.deliver_via_free_channels("msg")
        assert results == [{
            "channel": "whatsapp",
            "status": "failed",
            "error": "ALERT_RECIPIENT_PHONES is not configured",
        }]


class TestRainfallMessageThresholds:
    def test_below_thresholds_returns_none(self, monkeypatch):
        monkeypatch.setattr(notification.settings, "ALERT_RAINFALL_THRESHOLD_MM", 50)
        monkeypatch.setattr(notification.settings, "ALERT_FORECAST_RAINFALL_THRESHOLD_MM", 75)
        monkeypatch.setattr(notification.settings, "ALERT_LANDSLIDE_PROBABILITY_THRESHOLD", 0.7)
        req = notification.RainfallAlertRequest(
            location="Aizawl Ridge",
            observed_rainfall_mm=10,
            forecast_rainfall_mm=20,
            landslide_probability=0.2,
            excavation_active=False,
            alert_id=uuid4(),
        )
        assert notification._rainfall_alert_message(req) is None

    def test_observed_rain_triggers_message(self, monkeypatch):
        monkeypatch.setattr(notification.settings, "ALERT_RAINFALL_THRESHOLD_MM", 50)
        monkeypatch.setattr(notification.settings, "ALERT_FORECAST_RAINFALL_THRESHOLD_MM", 75)
        monkeypatch.setattr(notification.settings, "ALERT_LANDSLIDE_PROBABILITY_THRESHOLD", 0.7)
        req = notification.RainfallAlertRequest(
            location="Aizawl Ridge",
            observed_rainfall_mm=62,
            forecast_rainfall_mm=10,
            landslide_probability=0.1,
            excavation_active=False,
            alert_id=uuid4(),
        )
        message = notification._rainfall_alert_message(req)
        assert message is not None
        assert "62.0mm rain observed" in message
