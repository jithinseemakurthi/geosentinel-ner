"""Tests for Firebase Push, WhatsApp Meta Cloud API, and alert_recipient persistence."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from conftest import load_service_module

notification = load_service_module(
    "notification_advanced", "services/notification-service/app/main.py"
)
PushProvider = notification.PushProvider
WhatsAppProvider = notification.WhatsAppProvider
NotificationDispatcher = notification.NotificationDispatcher


# -----------------------------------------------------------------------------
# Push Provider Tests
# -----------------------------------------------------------------------------
class TestPushProvider:
    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        monkeypatch.setattr(notification.settings, "FIREBASE_PROJECT_ID", "geosentinel-test")

    async def test_send_push_mock_mode(self, monkeypatch):
        monkeypatch.setattr(notification.settings, "FIREBASE_PROJECT_ID", "geosentinel-test")
        provider = PushProvider()
        # Without credentials, it falls back to mock mode
        result = await provider.send("token_1234567890", "Risk High", "Landslide alert", {"alert_id": "123"})
        assert result["status"] == "sent"
        assert result["mode"] == "mock"
        assert "message_id" in result

    async def test_send_multicast_mock_mode(self):
        provider = PushProvider()
        result = await provider.send_multicast(["tok1", "tok2"], "Title", "Body", {})
        assert result["success_count"] == 2
        assert result["failure_count"] == 0
        assert result["invalid_tokens"] == []

    async def test_send_multicast_empty_tokens(self):
        provider = PushProvider()
        result = await provider.send_multicast([], "Title", "Body", {})
        assert result["success_count"] == 0
        assert result["failure_count"] == 0

    async def test_send_topic_mock_mode(self):
        provider = PushProvider()
        result = await provider.send_topic("district_aizawl", "Title", "Body", {})
        assert result["status"] == "sent"
        assert result["topic"] == "district_aizawl"
        assert result["mode"] == "mock"

    async def test_subscribe_and_unsubscribe_topic_mock(self):
        provider = PushProvider()
        sub_res = await provider.subscribe_to_topic(["tok1", "tok2"], "alerts_zone_1")
        assert sub_res["success_count"] == 2
        assert sub_res["topic"] == "alerts_zone_1"

        unsub_res = await provider.unsubscribe_from_topic(["tok1"], "alerts_zone_1")
        assert unsub_res["success_count"] == 1
        assert unsub_res["topic"] == "alerts_zone_1"

    async def test_missing_project_id_raises(self, monkeypatch):
        monkeypatch.setattr(notification.settings, "FIREBASE_PROJECT_ID", None)
        provider = PushProvider()
        with pytest.raises(RuntimeError, match="FIREBASE_PROJECT_ID"):
            await provider.send("tok", "t", "b", {})


# -----------------------------------------------------------------------------
# WhatsApp Meta Cloud API Tests
# -----------------------------------------------------------------------------
class TestWhatsAppMetaCloudAPI:
    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        monkeypatch.setattr(notification.settings, "WHATSAPP_PHONE_NUMBER_ID", "1000123456789")
        monkeypatch.setattr(notification.settings, "WHATSAPP_ACCESS_TOKEN", "EAAtesttoken123")

    async def test_send_template(self, monkeypatch):
        provider = WhatsAppProvider()
        recorded_payload = {}

        async def fake_post(payload):
            nonlocal recorded_payload
            recorded_payload = payload
            return {"messages": [{"id": "wamid.HBgL"}]}

        monkeypatch.setattr(provider, "_post", fake_post)
        result = await provider.send_template(
            to="+919876543210",
            template_name="landslide_warning_v2",
            language="en",
            params=["Aizawl", "High Risk"],
            header_params=["CRITICAL"],
            button_payloads=["ACK_ALERT"],
        )
        assert result["status"] == "sent"
        assert result["message_id"] == "wamid.HBgL"
        assert recorded_payload["messaging_product"] == "whatsapp"
        assert recorded_payload["type"] == "template"
        assert recorded_payload["template"]["name"] == "landslide_warning_v2"
        components = recorded_payload["template"]["components"]
        assert len(components) == 3
        assert components[0]["type"] == "header"
        assert components[1]["type"] == "body"
        assert components[2]["type"] == "button"

    async def test_send_text(self, monkeypatch):
        provider = WhatsAppProvider()
        recorded_payload = {}

        async def fake_post(payload):
            nonlocal recorded_payload
            recorded_payload = payload
            return {"messages": [{"id": "wamid.text123"}]}

        monkeypatch.setattr(provider, "_post", fake_post)
        result = await provider.send_text("+919876543210", "Alert: heavy rain predicted.")
        assert result["status"] == "sent"
        assert recorded_payload["type"] == "text"
        assert recorded_payload["text"]["body"] == "Alert: heavy rain predicted."

    async def test_send_interactive_buttons(self, monkeypatch):
        provider = WhatsAppProvider()
        recorded_payload = {}

        async def fake_post(payload):
            nonlocal recorded_payload
            recorded_payload = payload
            return {"messages": [{"id": "wamid.btn123"}]}

        monkeypatch.setattr(provider, "_post", fake_post)
        result = await provider.send_interactive_buttons(
            to="+919876543210",
            body_text="Are you safe?",
            buttons=[
                {"id": "safe_yes", "title": "I Am Safe"},
                {"id": "need_help", "title": "Need Help"},
            ],
            header_text="SAFETY CHECK",
            footer_text="GeoSentinel Emergency",
        )
        assert result["status"] == "sent"
        interactive = recorded_payload["interactive"]
        assert interactive["type"] == "button"
        assert len(interactive["action"]["buttons"]) == 2
        assert interactive["header"]["text"] == "SAFETY CHECK"

    async def test_send_interactive_list(self, monkeypatch):
        provider = WhatsAppProvider()
        recorded_payload = {}

        async def fake_post(payload):
            nonlocal recorded_payload
            recorded_payload = payload
            return {"messages": [{"id": "wamid.list123"}]}

        monkeypatch.setattr(provider, "_post", fake_post)
        result = await provider.send_interactive_list(
            to="+919876543210",
            body_text="Select nearest shelter:",
            button_text="View Shelters",
            sections=[
                {
                    "title": "Aizawl North",
                    "rows": [
                        {"id": "shelter_1", "title": "Community Hall A", "description": "Cap: 200"},
                    ],
                }
            ],
        )
        assert result["status"] == "sent"
        interactive = recorded_payload["interactive"]
        assert interactive["type"] == "list"
        assert interactive["action"]["button"] == "View Shelters"

    async def test_send_location(self, monkeypatch):
        provider = WhatsAppProvider()
        recorded_payload = {}

        async def fake_post(payload):
            nonlocal recorded_payload
            recorded_payload = payload
            return {"messages": [{"id": "wamid.loc123"}]}

        monkeypatch.setattr(provider, "_post", fake_post)
        result = await provider.send_location(
            to="+919876543210",
            latitude=23.7271,
            longitude=92.7176,
            name="Aizawl Relief Center",
            address="Khatla, Aizawl",
        )
        assert result["status"] == "sent"
        assert recorded_payload["type"] == "location"
        assert recorded_payload["location"]["latitude"] == 23.7271

    async def test_send_media(self, monkeypatch):
        provider = WhatsAppProvider()
        recorded_payload = {}

        async def fake_post(payload):
            nonlocal recorded_payload
            recorded_payload = payload
            return {"messages": [{"id": "wamid.media123"}]}

        monkeypatch.setattr(provider, "_post", fake_post)
        result = await provider.send_media(
            to="+919876543210",
            media_type="image",
            media_url="https://minio.geosentinel.internal/rasters/hazard_map.png",
            caption="Hazard map for your sector",
        )
        assert result["status"] == "sent"
        assert recorded_payload["type"] == "image"
        assert recorded_payload["image"]["link"].endswith("hazard_map.png")

    async def test_missing_credentials_raises(self, monkeypatch):
        monkeypatch.setattr(notification.settings, "WHATSAPP_ACCESS_TOKEN", None)
        provider = WhatsAppProvider()
        with pytest.raises(RuntimeError, match="WHATSAPP_ACCESS_TOKEN"):
            await provider.send_text("+919876543210", "Hello")


# -----------------------------------------------------------------------------
# Alert Recipient Persistence & SQL Tests
# -----------------------------------------------------------------------------
class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        return self._rows[0]["id"]


class FakeSession:
    def __init__(self):
        self.executed = []
        self.inserted = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append((sql, params))
        if "INSERT INTO alert_recipient" in sql:
            self.inserted.append(params)
            return FakeResult([{"id": uuid4()}])
        if "SELECT id, alert_id" in sql:
            return FakeResult([
                {
                    "id": uuid4(),
                    "alert_id": params.get("alert_id") if params else uuid4(),
                    "recipient_type": "user",
                    "recipient_id": "+919876543210",
                    "channel": "sms",
                    "sent_at": datetime.now(timezone.utc),
                    "delivered_at": None,
                    "read_at": None,
                    "status": "sent",
                    "error_message": None,
                    "retry_count": 0,
                }
            ])
        if "UPDATE alert_recipient" in sql:
            return FakeResult([{"id": uuid4(), "status": "delivered"}])
        return FakeResult([])

    async def flush(self):
        pass

    async def commit(self):
        pass


class TestAlertRecipientPersistence:
    async def test_dispatcher_logs_delivery_on_conflict_update(self):
        session = FakeSession()
        dispatcher = NotificationDispatcher(session)
        alert_id = uuid4()
        recipient = {"id": "+919876543210", "type": "user", "contact": "+919876543210"}
        result = {"status": "sent", "provider_id": "sms_123"}

        await dispatcher._log_delivery(alert_id, recipient, "sms", result)
        assert len(session.inserted) == 1
        record = session.inserted[0]
        assert record["alert_id"] == alert_id
        assert record["channel"] == "sms"
        assert record["status"] == "sent"
        assert record["sent_at"] is not None

    async def test_dispatcher_logs_failure_correctly(self):
        session = FakeSession()
        dispatcher = NotificationDispatcher(session)
        alert_id = uuid4()
        recipient = {"id": "+919876543210", "type": "user", "contact": "+919876543210"}
        result = {"status": "failed", "error": "Gateway timeout"}

        await dispatcher._log_delivery(alert_id, recipient, "sms", result)
        assert len(session.inserted) == 1
        record = session.inserted[0]
        assert record["status"] == "failed"
        assert record["error_message"] == "Gateway timeout"
        assert record["sent_at"] is None

    async def test_dispatch_full_cycle(self, monkeypatch):
        session = FakeSession()
        dispatcher = NotificationDispatcher(session)
        alert_id = uuid4()
        recipients = [
            {
                "id": "+919876543210",
                "contact": "+919876543210",
                "channels": ["sms"],
            }
        ]
        templates = {"sms": "Flood warning in your area."}
        mock_send = AsyncMock(return_value={"status": "sent", "provider_message_id": "p1"})
        monkeypatch.setattr(notification.sms_provider, "send", mock_send)

        res = await dispatcher.dispatch(alert_id, recipients, templates, "critical")
        assert res["total"] == 1
        assert res["sent"] == 1
        assert res["failed"] == 0
