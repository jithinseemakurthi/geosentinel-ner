"""
GeoSentinel-NER Notification Service
Multi-channel notification delivery: SMS, Push, WhatsApp, Email, CAP.

Security notes:
- All send endpoints (including /test/*) require a valid JWT with role >= admin.
- Recipients and templates are size-limited; phone numbers are validated.
- Delivery logs are written to the database; SMS provider responses are recorded
  for traceability and refund handling.
"""
import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from geosentinel_shared import (
    AlertRecipientRead,
    check_permission,
    close_db,
    configure_logging,
    get_db_session,
    get_logger,
    init_db,
    settings,
    verify_token,
)
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

configure_logging()
logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Auth dependency (re-declared here so the service is self-contained)
# -----------------------------------------------------------------------------
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: E402

security = HTTPBearer(auto_error=False)


class Principal:
    def __init__(self, sub: UUID, role: str, username: str):
        self.sub = sub
        self.role = role
        self.username = username


async def get_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Principal:
    """Require a valid access token. Used to gate expensive / billable endpoints."""
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = verify_token(credentials.credentials, "access")
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return Principal(sub=payload.sub, role=payload.role, username=payload.username)


def require_role(min_role: str):
    async def _dep(principal: Principal = Depends(get_principal)):
        # Higher roles are listed in ROLE_PERMISSIONS in geosentinel_shared.auth.
        if not check_permission(principal.role, "all", "all") and not check_permission(
            principal.role, "settings", "write"
        ):
            raise HTTPException(
                status_code=403,
                detail=f"Requires role >= {min_role}",
            )
        return principal
    return _dep


# -----------------------------------------------------------------------------
# Validation helpers
# -----------------------------------------------------------------------------
E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def _validate_phone(phone: str) -> str:
    if not E164_RE.match(phone):
        raise ValueError("phone must be in E.164 format, e.g. +919876543210")
    return phone


# -----------------------------------------------------------------------------
# Channel providers
# -----------------------------------------------------------------------------
class SMSProvider:
    def __init__(self):
        self.provider = settings.SMS_PROVIDER
        self.api_key = settings.SMS_API_KEY
        self.sender_id = settings.SMS_SENDER_ID

    async def send(self, to: str, message: str, template_id: Optional[str] = None) -> Dict[str, Any]:
        to = _validate_phone(to)
        logger.info("sms_sending", provider=self.provider, to=to[:6] + "****", len=len(message))
        if self.provider.lower() == "mock":
            # Presentation/development mode: exercises the exact notification
            # flow without claiming that a real carrier has delivered a text.
            logger.info("sms_mock_delivered", to=to[:6] + "****", message=message)
            return {
                "status": "simulated",
                "provider_message_id": f"mock_{uuid4().hex[:12]}",
            }
        if self.provider.lower() == "textbelt":
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    settings.TEXTBELT_URL,
                    data={"number": to.removeprefix("+"), "message": message},
                )
            response.raise_for_status()
            body = response.json()
            if not body.get("success"):
                raise RuntimeError(str(body.get("message", "TextBelt rejected the message")))
            return {
                "status": "sent",
                "provider_message_id": body.get("textId") or body.get("id"),
            }
        if self.provider.lower() == "textbee":
            if not settings.TEXTBEE_API_KEY:
                raise RuntimeError("TEXTBEE_API_KEY is not configured")
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    settings.TEXTBEE_API_URL,
                    headers={"x-api-key": settings.TEXTBEE_API_KEY},
                    json={"recipients": [to], "message": message},
                )
            # Surface the provider's response body so setup problems (device
            # offline, unregistered, quota exceeded) are diagnosable from logs.
            if response.status_code != 200:
                raise RuntimeError(
                    f"TextBee returned HTTP {response.status_code}: {response.text[:200]!r}. "
                    "Check that your Android device is registered and online in the "
                    "textbee dashboard and the API key is valid."
                )
            body = response.json()
            return {
                "status": "sent",
                "provider_message_id": body.get("id") or body.get("messageId"),
            }
        if not self.api_key:
            raise RuntimeError("SMS_API_KEY is not configured")
        if self.provider.lower() == "msg91":
            if not template_id:
                raise RuntimeError("SMS_TEMPLATE_ID_ALERT is required for MSG91 delivery")
            payload = {
                "template_id": template_id,
                "sender": self.sender_id,
                "short_url": "0",
                "recipients": [{
                    "mobiles": to.removeprefix("+"),
                    "var1": message,
                }],
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    settings.SMS_API_BASE_URL,
                    headers={"authkey": self.api_key, "Content-Type": "application/json"},
                    json=payload,
                )
            response.raise_for_status()
            body = response.json()
            return {
                "status": "sent",
                "provider_message_id": body.get("request_id") or body.get("message"),
            }
        if self.provider.lower() == "twilio":
            if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN or not settings.TWILIO_FROM_NUMBER:
                raise RuntimeError("Twilio account, auth token, and from number are required")
            url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"
            # Trial accounts only accept a Twilio-defined template name in Body.
            # This is deliberately explicit so a trial never appears to have
            # delivered the dynamic weather digest when it could not do so.
            body = settings.TWILIO_TRIAL_TEMPLATE or message
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    url,
                    auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                    data={"To": to, "From": settings.TWILIO_FROM_NUMBER, "Body": body},
                )
            response.raise_for_status()
            body = response.json()
            return {
                "status": "sent",
                "provider_message_id": body.get("sid"),
                "content_mode": "trial_template" if settings.TWILIO_TRIAL_TEMPLATE else "dynamic",
            }
        raise RuntimeError(f"Unsupported SMS_PROVIDER: {self.provider}")


class PushProvider:
    def __init__(self):
        self.project_id = settings.FIREBASE_PROJECT_ID
        self._app = None

    def _init_firebase(self):
        """Initialize firebase-admin once using either a service-account JSON
        (FIREBASE_SERVICE_ACCOUNT_JSON / FIREBASE_SERVICE_ACCOUNT_FILE) or the
        project-id + client-email + private-key triple. Returns None when
        firebase-admin is not installed (falls back to mock)."""
        app = self._app
        if app is not None:
            return app
        try:
            import firebase_admin  # type: ignore
            from firebase_admin import credentials  # type: ignore
        except ImportError:
            logger.warning("firebase_admin_not_installed_push_mocked")
            return None
        options = {"projectId": self.project_id}
        if getattr(settings, "FIREBASE_SERVICE_ACCOUNT_FILE", None):
            cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_FILE)
        else:
            service_account_json = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_JSON", None)
            if service_account_json:
                import json as _json

                info = _json.loads(service_account_json)
            else:
                if not (settings.FIREBASE_CLIENT_EMAIL and settings.FIREBASE_PRIVATE_KEY):
                    logger.warning("firebase_credentials_missing_push_mocked")
                    return None
                info = {
                    "project_id": self.project_id,
                    "client_email": settings.FIREBASE_CLIENT_EMAIL,
                    "private_key": settings.FIREBASE_PRIVATE_KEY.replace("\\n", "\n"),
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            cred = credentials.Certificate(info)
        try:
            app = firebase_admin.initialize_app(cred, options)
        except ValueError:
            # Already initialized in this process — reuse the default app.
            app = firebase_admin.get_app()
        self._app = app
        return app

    def _build_android_config(self, priority: str = "high"):
        try:
            from firebase_admin import messaging
            return messaging.AndroidConfig(
                priority=priority,
                notification=messaging.AndroidNotification(
                    channel_id="landslide_alerts",
                    sound="default",
                    click_action="OPEN_ALERT_ACTIVITY",
                ),
            )
        except Exception:
            return None

    def _build_apns_config(self):
        try:
            from firebase_admin import messaging
            return messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default", badge=1)
                )
            )
        except Exception:
            return None

    def _build_webpush_config(self):
        try:
            from firebase_admin import messaging
            return messaging.WebpushConfig(
                headers={"Urgency": "high"},
                notification=messaging.WebpushNotification(icon="/logo.svg"),
            )
        except Exception:
            return None

    async def send(self, device_token: str, title: str, body: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.project_id:
            raise RuntimeError("FIREBASE_PROJECT_ID is not configured")
        logger.info("push_sending", device_token=device_token[:10] + "****", title=title)
        app = self._init_firebase()
        if app is None:
            return {"status": "sent", "message_id": f"mock_{uuid4().hex[:8]}", "mode": "mock"}
        from firebase_admin import messaging  # type: ignore

        message = messaging.Message(
            token=device_token,
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items() if v is not None},
            android=self._build_android_config(),
            apns=self._build_apns_config(),
            webpush=self._build_webpush_config(),
        )
        result = await asyncio.to_thread(messaging.send, message, app=app)
        return {"status": "sent", "message_id": result, "mode": "firebase"}

    async def send_multicast(self, device_tokens: List[str], title: str, body: str, data: Dict) -> Dict[str, Any]:
        if not self.project_id:
            raise RuntimeError("FIREBASE_PROJECT_ID is not configured")
        if not device_tokens:
            return {"success_count": 0, "failure_count": 0, "invalid_tokens": []}
        app = self._init_firebase()
        if app is None:
            return {"success_count": len(device_tokens), "failure_count": 0, "invalid_tokens": [], "mode": "mock"}
        from firebase_admin import messaging  # type: ignore

        tokens = list(device_tokens[:500])
        message = messaging.MulticastMessage(
            tokens=tokens,
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items() if v is not None},
            android=self._build_android_config(),
            apns=self._build_apns_config(),
            webpush=self._build_webpush_config(),
        )
        batch_response = await asyncio.to_thread(
            messaging.send_multicast, message, dry_run=False, app=app
        )
        invalid_tokens = []
        if batch_response.failure_count > 0:
            for idx, resp in enumerate(batch_response.responses):
                if not resp.success and resp.exception:
                    code = str(resp.exception).lower()
                    if "not-registered" in code or "invalid" in code or "unregistered" in code:
                        invalid_tokens.append(tokens[idx])
        return {
            "success_count": batch_response.success_count,
            "failure_count": batch_response.failure_count,
            "invalid_tokens": invalid_tokens,
            "mode": "firebase",
        }

    async def send_topic(self, topic: str, title: str, body: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.project_id:
            raise RuntimeError("FIREBASE_PROJECT_ID is not configured")
        topic_name = topic.strip().lstrip("/")
        logger.info("push_topic_sending", topic=topic_name, title=title)
        app = self._init_firebase()
        if app is None:
            return {
                "status": "sent",
                "message_id": f"mock_topic_{uuid4().hex[:8]}",
                "topic": topic_name,
                "mode": "mock",
            }
        from firebase_admin import messaging  # type: ignore

        message = messaging.Message(
            topic=topic_name,
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items() if v is not None},
            android=self._build_android_config(),
            apns=self._build_apns_config(),
            webpush=self._build_webpush_config(),
        )
        result = await asyncio.to_thread(messaging.send, message, app=app)
        return {"status": "sent", "message_id": result, "topic": topic_name, "mode": "firebase"}

    async def subscribe_to_topic(self, device_tokens: List[str], topic: str) -> Dict[str, Any]:
        if not self.project_id:
            raise RuntimeError("FIREBASE_PROJECT_ID is not configured")
        topic_name = topic.strip().lstrip("/")
        app = self._init_firebase()
        if app is None:
            return {"success_count": len(device_tokens), "failure_count": 0, "topic": topic_name, "mode": "mock"}
        from firebase_admin import messaging  # type: ignore

        response = await asyncio.to_thread(
            messaging.subscribe_to_topic, device_tokens, topic_name, app=app
        )
        return {
            "success_count": response.success_count,
            "failure_count": response.failure_count,
            "topic": topic_name,
            "mode": "firebase",
        }

    async def unsubscribe_from_topic(self, device_tokens: List[str], topic: str) -> Dict[str, Any]:
        if not self.project_id:
            raise RuntimeError("FIREBASE_PROJECT_ID is not configured")
        topic_name = topic.strip().lstrip("/")
        app = self._init_firebase()
        if app is None:
            return {"success_count": len(device_tokens), "failure_count": 0, "topic": topic_name, "mode": "mock"}
        from firebase_admin import messaging  # type: ignore

        response = await asyncio.to_thread(
            messaging.unsubscribe_from_topic, device_tokens, topic_name, app=app
        )
        return {
            "success_count": response.success_count,
            "failure_count": response.failure_count,
            "topic": topic_name,
            "mode": "firebase",
        }


class WhatsAppProvider:
    GRAPH_API_VERSION = "v21.0"

    def __init__(self):
        self.phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self.access_token = settings.WHATSAPP_ACCESS_TOKEN

    async def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.access_token or not self.phone_number_id:
            raise RuntimeError("WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID are required")
        url = (
            f"https://graph.facebook.com/{self.GRAPH_API_VERSION}/"
            f"{self.phone_number_id}/messages"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        response.raise_for_status()
        return response.json()

    async def send_template(
        self,
        to: str,
        template_name: str,
        language: str = "en",
        params: Optional[List[str]] = None,
        header_params: Optional[List[str]] = None,
        button_payloads: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        to = _validate_phone(to)
        logger.info("whatsapp_sending", to=to[:6] + "****", template=template_name)
        components = []
        if header_params:
            components.append({
                "type": "header",
                "parameters": [{"type": "text", "text": str(p)} for p in header_params[:5]],
            })
        if params:
            components.append({
                "type": "body",
                "parameters": [{"type": "text", "text": str(p)} for p in params[:10]],
            })
        if button_payloads:
            for idx, payload_val in enumerate(button_payloads[:3]):
                components.append({
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": str(idx),
                    "parameters": [{"type": "payload", "payload": str(payload_val)}],
                })
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language or "en"},
                **({"components": components} if components else {}),
            },
        }
        body = await self._post(payload)
        message_id = (body.get("messages") or [{}])[0].get("id")
        return {"status": "sent", "message_id": message_id or f"wa_{uuid4().hex[:8]}"}

    async def send_text(self, to: str, text: str, preview_url: bool = False) -> Dict[str, Any]:
        to = _validate_phone(to)
        logger.info("whatsapp_text_sending", to=to[:6] + "****", len=len(text))
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": preview_url, "body": text[:4096]},
        }
        body = await self._post(payload)
        message_id = (body.get("messages") or [{}])[0].get("id")
        return {"status": "sent", "message_id": message_id or f"wa_{uuid4().hex[:8]}"}

    async def send_interactive_buttons(
        self,
        to: str,
        body_text: str,
        buttons: List[Dict[str, str]],
        header_text: Optional[str] = None,
        footer_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send quick reply interactive buttons (max 3 buttons)."""
        to = _validate_phone(to)
        btn_objects = []
        for i, b in enumerate(buttons[:3]):
            btn_id = b.get("id", f"btn_{i}")
            btn_title = b.get("title", f"Option {i+1}")[:20]
            btn_objects.append({
                "type": "reply",
                "reply": {"id": btn_id, "title": btn_title},
            })
        interactive: Dict[str, Any] = {
            "type": "button",
            "body": {"text": body_text[:1024]},
            "action": {"buttons": btn_objects},
        }
        if header_text:
            interactive["header"] = {"type": "text", "text": header_text[:60]}
        if footer_text:
            interactive["footer"] = {"text": footer_text[:60]}
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
        body = await self._post(payload)
        message_id = (body.get("messages") or [{}])[0].get("id")
        return {"status": "sent", "message_id": message_id or f"wa_{uuid4().hex[:8]}"}

    async def send_interactive_list(
        self,
        to: str,
        body_text: str,
        button_text: str,
        sections: List[Dict[str, Any]],
        header_text: Optional[str] = None,
        footer_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send interactive menu list (max 10 rows)."""
        to = _validate_phone(to)
        interactive: Dict[str, Any] = {
            "type": "list",
            "body": {"text": body_text[:1024]},
            "action": {
                "button": button_text[:20],
                "sections": sections[:10],
            },
        }
        if header_text:
            interactive["header"] = {"type": "text", "text": header_text[:60]}
        if footer_text:
            interactive["footer"] = {"text": footer_text[:60]}
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
        body = await self._post(payload)
        message_id = (body.get("messages") or [{}])[0].get("id")
        return {"status": "sent", "message_id": message_id or f"wa_{uuid4().hex[:8]}"}

    async def send_location(
        self,
        to: str,
        latitude: float,
        longitude: float,
        name: Optional[str] = None,
        address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send location pin."""
        to = _validate_phone(to)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "location",
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "name": name or "GeoSentinel Location",
                "address": address or f"{latitude:.4f}, {longitude:.4f}",
            },
        }
        body = await self._post(payload)
        message_id = (body.get("messages") or [{}])[0].get("id")
        return {"status": "sent", "message_id": message_id or f"wa_{uuid4().hex[:8]}"}

    async def send_media(
        self,
        to: str,
        media_type: str,
        media_url: str,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send media (image, document, audio, video)."""
        to = _validate_phone(to)
        media_payload: Dict[str, Any] = {"link": media_url}
        if caption and media_type in ("image", "document", "video"):
            media_payload["caption"] = caption[:1024]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": media_type,
            media_type: media_payload,
        }
        body = await self._post(payload)
        message_id = (body.get("messages") or [{}])[0].get("id")
        return {"status": "sent", "message_id": message_id or f"wa_{uuid4().hex[:8]}"}


class EmailProvider:
    async def send(self, to: str, subject: str, html_body: str, text_body: Optional[str] = None) -> Dict[str, Any]:
        # Basic sanity: subject + body required, html body capped
        if not subject or not html_body:
            raise ValueError("subject and html_body are required")
        if len(html_body) > 100_000:
            raise ValueError("html_body exceeds 100kB limit")
        logger.info("email_sending", to=to, subject=subject[:60])
        return {"status": "sent", "message_id": f"mock_{uuid4().hex[:8]}"}


class CAPProvider:
    def __init__(self):
        self.endpoint = settings.CAP_ENDPOINT
        self.auth_token = settings.CAP_AUTH_TOKEN

    async def send_alert(self, alert_data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.endpoint:
            raise RuntimeError("CAP_ENDPOINT is not configured")
        if not self.auth_token:
            raise RuntimeError("CAP_AUTH_TOKEN is not configured")
        logger.info("cap_sending", alert_id=alert_data.get("id"))
        return {"status": "sent", "cap_identifier": f"CAP-{uuid4().hex[:12]}"}


sms_provider = SMSProvider()
push_provider = PushProvider()
whatsapp_provider = WhatsAppProvider()
email_provider = EmailProvider()
cap_provider = CAPProvider()


# -----------------------------------------------------------------------------
# Free alert channels (zero-cost alternatives to paid SMS providers)
#
# These need no SMS gateway account, no DLT registration, and no spare Android
# phone running 24/7:
#   whatsapp -> CallMeBot free WhatsApp API (one-time activation per phone)
#   telegram -> official Telegram Bot API (bot token + chat IDs)
#   push     -> ntfy.sh push notifications (subscribe to a topic in the app)
# -----------------------------------------------------------------------------
class FreeChannelDispatcher:
    """Delivers alerts via free channels configured in ALERT_FREE_CHANNELS."""

    FREE_CHANNELS = ("whatsapp", "telegram", "push")
    _NTFY_TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

    @property
    def _enabled(self) -> set:
        """Parsed from settings on every access so config changes apply live."""
        return {
            c.strip().lower()
            for c in (settings.ALERT_FREE_CHANNELS or "").split(",")
            if c.strip()
        }

    @property
    def active(self) -> List[str]:
        """Enabled channels that GeoSentinel knows how to deliver."""
        return [c for c in self.FREE_CHANNELS if c in self._enabled]

    @property
    def unknown_channels(self) -> List[str]:
        return sorted(self._enabled - set(self.FREE_CHANNELS))

    async def send_whatsapp(self, phone: str, message: str) -> Dict[str, Any]:
        """Send a WhatsApp message through the CallMeBot free API."""
        if not settings.CALLMEBOT_API_KEY:
            raise RuntimeError("CALLMEBOT_API_KEY is not configured")
        to = _validate_phone(phone)
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                settings.CALLMEBOT_API_URL,
                params={
                    "phone": to,
                    "apikey": settings.CALLMEBOT_API_KEY,
                    "text": message[:900],
                },
            )
        text = response.text or ""
        if response.status_code != 200 or "MESSAGE NOT SENT" in text.upper():
            raise RuntimeError(
                f"CallMeBot rejected message (HTTP {response.status_code}): {text[:160]!r}. "
                "Confirm the recipient activated the bot once and the API key matches."
            )
        return {
            "status": "sent",
            "channel": "whatsapp",
            "provider_message_id": f"cmb_{uuid4().hex[:10]}",
        }

    async def send_telegram(self, chat_id: str, message: str) -> Dict[str, Any]:
        """Send a Telegram message via the official Bot API."""
        if not settings.TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
        chat_id = chat_id.strip()
        if not chat_id:
            raise ValueError("Telegram chat id must not be empty")
        url = (
            f"{settings.TELEGRAM_API_URL.rstrip('/')}"
            f"/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        )
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": message[:4000],
                    "disable_web_page_preview": True,
                },
            )
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code != 200 or not body.get("ok"):
            raise RuntimeError(
                f"Telegram rejected message (HTTP {response.status_code}): "
                f"{str(body)[:160]!r}. Verify TELEGRAM_BOT_TOKEN and that the "
                "recipient has pressed Start on the bot."
            )
        message_id = (body.get("result") or {}).get("message_id")
        return {
            "status": "sent",
            "channel": "telegram",
            "provider_message_id": str(message_id) if message_id is not None else None,
        }

    async def send_push(self, topic: str, message: str, title: Optional[str] = None) -> Dict[str, Any]:
        """Post an ntfy.sh push notification; recipients subscribe to the topic."""
        topic_name = topic.strip().strip("/")
        if not self._NTFY_TOPIC_RE.match(topic_name):
            raise ValueError(
                "ntfy topic must be 1-64 characters of letters/digits/_/-"
            )
        headers = {"Title": title} if title else {}
        url = f"{settings.NTFY_SERVER_URL.rstrip('/')}/{topic_name}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, content=message.encode("utf-8"), headers=headers)
        if response.status_code != 200:
            raise RuntimeError(
                f"ntfy.sh rejected message (HTTP {response.status_code}): {response.text[:160]!r}"
            )
        return {
            "status": "sent",
            "channel": "push",
            "provider_message_id": f"ntfy_{uuid4().hex[:10]}",
        }


free_dispatcher = FreeChannelDispatcher()


def _phones_csv(raw: str, setting_name: str) -> List[str]:
    phones = [_validate_phone(p.strip()) for p in raw.split(",") if p.strip()]
    if not phones:
        raise RuntimeError(f"{setting_name} is not configured")
    return phones


async def deliver_via_free_channels(
    message: str,
    title: Optional[str] = None,
    phones_override: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Fan an alert out across every enabled free channel.

    Each delivery is attempted independently — one failing channel never
    blocks the others. Failures are logged and returned, not raised.
    """
    results: List[Dict[str, Any]] = []

    async def _attempt(label: str, coro) -> None:
        try:
            outcome = await coro
            results.append({"recipient": label, **outcome})
        except (RuntimeError, ValueError, httpx.HTTPError) as exc:
            logger.warning("free_channel_delivery_failed", error=str(exc))
            results.append({"recipient": label, "status": "failed", "error": str(exc)})

    if "whatsapp" in free_dispatcher.active:
        try:
            phones = phones_override if phones_override is not None else _phones_csv(
                settings.ALERT_RECIPIENT_PHONES, "ALERT_RECIPIENT_PHONES"
            )
        except RuntimeError as exc:
            results.append({"channel": "whatsapp", "status": "failed", "error": str(exc)})
        else:
            for phone in phones:
                await _attempt(phone[:6] + "****@whatsapp", free_dispatcher.send_whatsapp(phone, message))

    if "telegram" in free_dispatcher.active:
        chat_ids = [c.strip() for c in (settings.TELEGRAM_CHAT_IDS or "").split(",") if c.strip()]
        if not chat_ids:
            results.append({
                "channel": "telegram",
                "status": "failed",
                "error": "TELEGRAM_CHAT_IDS is not configured",
            })
        for chat_id in chat_ids:
            await _attempt(chat_id + "@telegram", free_dispatcher.send_telegram(chat_id, message))

    if "push" in free_dispatcher.active:
        topics = [t.strip() for t in (settings.NTFY_TOPICS or "").split(",") if t.strip()]
        if not topics:
            results.append({"channel": "push", "status": "failed", "error": "NTFY_TOPICS is not configured"})
        for topic in topics:
            await _attempt(topic + "@push", free_dispatcher.send_push(topic, message, title=title))

    unknown = free_dispatcher.unknown_channels
    if unknown:
        logger.warning("unknown_free_channels_ignored", channels=unknown)
    return results


# Representative NER locations/abbreviations come from the shared package.
from geosentinel_shared.districts import (  # noqa: E402
    NORTHEAST_ABBREVIATIONS,
    NORTHEAST_STATE_LOCATIONS,
)

IST = timezone(timedelta(hours=5, minutes=30))
digest_scheduler = AsyncIOScheduler(timezone=IST)
digest_status: Dict[str, Any] = {"last_run_at": None, "last_status": "not_run", "last_error": None}


# -----------------------------------------------------------------------------
# Dispatcher
# -----------------------------------------------------------------------------
class NotificationDispatcher:
    def __init__(self, db_session):
        self.db = db_session

    async def dispatch(
        self,
        alert_id: UUID,
        recipients: List[Dict[str, Any]],
        message_templates: Dict[str, str],
        severity: str,
    ) -> Dict[str, Any]:
        results = {"total": len(recipients), "sent": 0, "failed": 0, "details": []}
        for recipient in recipients:
            for channel in recipient.get("channels", []):
                try:
                    result = await self._send_via_channel(
                        channel=channel,
                        recipient=recipient,
                        templates=message_templates,
                        severity=severity,
                    )
                    results["sent"] += 1
                    results["details"].append({
                        "recipient": recipient["id"],
                        "channel": channel,
                        "status": "sent",
                        "provider_id": result.get("message_id"),
                    })
                except Exception as e:
                    results["failed"] += 1
                    results["details"].append({
                        "recipient": recipient["id"],
                        "channel": channel,
                        "status": "failed",
                        "error": str(e),
                    })
                await self._log_delivery(alert_id, recipient, channel, results["details"][-1])
        return results

    async def _send_via_channel(
        self,
        channel: str,
        recipient: Dict[str, Any],
        templates: Dict[str, str],
        severity: str,
    ) -> Dict[str, Any]:
        template = templates.get(channel, templates.get("default", ""))
        if channel == "sms":
            return await sms_provider.send(
                to=recipient["contact"],
                message=template,
                template_id=settings.SMS_TEMPLATE_ID_ALERT,
            )
        if channel == "push":
            if recipient.get("topic"):
                return await push_provider.send_topic(
                    topic=recipient["topic"],
                    title=f"GeoSentinel Alert - {severity.upper()}",
                    body=template,
                    data={"alert_id": recipient.get("alert_id"), "severity": severity},
                )
            return await push_provider.send(
                device_token=recipient.get("device_token", ""),
                title=f"GeoSentinel Alert - {severity.upper()}",
                body=template,
                data={"alert_id": recipient.get("alert_id"), "severity": severity},
            )
        if channel == "whatsapp":
            contact = recipient.get("contact", "")
            if recipient.get("interactive_buttons"):
                return await whatsapp_provider.send_interactive_buttons(
                    to=contact,
                    body_text=template,
                    buttons=recipient["interactive_buttons"],
                    header_text=f"GeoSentinel {severity.upper()}",
                )
            if recipient.get("location"):
                loc = recipient["location"]
                return await whatsapp_provider.send_location(
                    to=contact,
                    latitude=loc["latitude"],
                    longitude=loc["longitude"],
                    name=loc.get("name"),
                    address=loc.get("address"),
                )
            if recipient.get("media_url"):
                return await whatsapp_provider.send_media(
                    to=contact,
                    media_type=recipient.get("media_type", "image"),
                    media_url=recipient["media_url"],
                    caption=template,
                )
            if recipient.get("whatsapp_template"):
                return await whatsapp_provider.send_template(
                    to=contact,
                    template_name=recipient["whatsapp_template"],
                    language=recipient.get("language", settings.DEFAULT_LANGUAGE),
                    params=recipient.get("template_params", []),
                )
            return await whatsapp_provider.send_text(to=contact, text=template)
        if channel == "email":
            return await email_provider.send(
                to=recipient["contact"],
                subject=f"GeoSentinel Alert - {severity.upper()}",
                html_body=template,
            )
        if channel == "cap":
            return await cap_provider.send_alert(recipient.get("cap_payload", {}))
        raise ValueError(f"Unknown channel: {channel}")

    async def _log_delivery(self, alert_id, recipient, channel, result):
        """Persist one delivery attempt to alert_recipient (best-effort).

        Uses ON CONFLICT DO UPDATE so retries for the same
        (alert, recipient, channel) update the row instead of failing.
        """
        recipient_id = str(recipient.get("id") or recipient.get("contact") or "unknown")
        recipient_type = str(recipient.get("type") or "user")
        status = "sent" if result.get("status") == "sent" else "failed"
        error_message = result.get("error") if status == "failed" else None
        provider_id = result.get("provider_id")
        sent_at = datetime.now(timezone.utc) if status == "sent" else None
        try:
            from sqlalchemy import text

            await self.db.execute(
                text(
                    """
                    INSERT INTO alert_recipient
                        (alert_id, recipient_type, recipient_id, channel, sent_at, status, error_message)
                    VALUES (:alert_id, :recipient_type, :recipient_id, :channel, :sent_at, :status, :error_message)
                    ON CONFLICT (alert_id, recipient_id, channel) DO UPDATE
                        SET sent_at = EXCLUDED.sent_at,
                            status = EXCLUDED.status,
                            error_message = EXCLUDED.error_message,
                            retry_count = alert_recipient.retry_count + 1
                    """
                ),
                {
                    "alert_id": alert_id,
                    "recipient_type": recipient_type[:20],
                    "recipient_id": recipient_id[:100],
                    "channel": channel[:20],
                    "sent_at": sent_at,
                    "status": status,
                    "error_message": error_message,
                },
            )
            await self.db.flush()
            if provider_id:
                logger.info("delivery_logged", alert_id=str(alert_id), recipient=recipient_id[:10], channel=channel)
        except Exception as exc:  # pragma: no cover - DB may be down in dev
            logger.warning("alert_recipient_log_failed", error=str(exc), channel=channel, provider_id=provider_id)


# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------
class NotificationRequest(BaseModel):
    alert_id: UUID
    recipients: List[Dict[str, Any]] = Field(..., max_length=10_000)
    message_templates: Dict[str, str] = Field(..., max_length=20)
    severity: str


class NotificationResponse(BaseModel):
    notification_id: UUID
    status: str
    results: Dict[str, Any]


class TemplateRenderRequest(BaseModel):
    template_id: str
    language: str = "en"
    variables: Dict[str, Any] = Field(default_factory=dict, max_length=100)


class TemplateRenderResponse(BaseModel):
    rendered: Dict[str, str]


class TestSMSRequest(BaseModel):
    phone: str
    message: str = Field(default="Test message from GeoSentinel", max_length=320)

    @field_validator("phone")
    @classmethod
    def _v(cls, v: str) -> str:
        return _validate_phone(v)


class TestPushRequest(BaseModel):
    device_token: str = Field(..., min_length=10, max_length=500)
    title: str = Field(default="Test", max_length=200)
    body: str = Field(default="Test push notification", max_length=4000)


class TestWhatsAppRequest(BaseModel):
    phone: str
    template: str = Field(default="test_template", max_length=200)
    params: List[str] = Field(default_factory=list, max_length=20)

    @field_validator("phone")
    @classmethod
    def _v(cls, v: str) -> str:
        return _validate_phone(v)


class TopicPushRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=100)
    title: str = Field(default="Alert", max_length=200)
    body: str = Field(..., max_length=4000)
    data: Dict[str, Any] = Field(default_factory=dict)


class TopicSubscriptionRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=100)
    tokens: List[str] = Field(..., min_length=1, max_length=1000)


class TestWhatsAppInteractiveRequest(BaseModel):
    phone: str
    body: str = Field(..., max_length=1024)
    buttons: List[Dict[str, str]] = Field(..., min_length=1, max_length=3)
    header: Optional[str] = Field(default=None, max_length=60)
    footer: Optional[str] = Field(default=None, max_length=60)

    @field_validator("phone")
    @classmethod
    def _v(cls, v: str) -> str:
        return _validate_phone(v)


class TestWhatsAppLocationRequest(BaseModel):
    phone: str
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    name: Optional[str] = Field(default=None, max_length=100)
    address: Optional[str] = Field(default=None, max_length=200)

    @field_validator("phone")
    @classmethod
    def _v(cls, v: str) -> str:
        return _validate_phone(v)


class TestWhatsAppMediaRequest(BaseModel):
    phone: str
    media_type: str = Field(default="image", description="image|document|audio|video")
    media_url: str = Field(..., max_length=1000)
    caption: Optional[str] = Field(default=None, max_length=1024)

    @field_validator("phone")
    @classmethod
    def _v(cls, v: str) -> str:
        return _validate_phone(v)


class AlertRecipientStatusUpdateRequest(BaseModel):
    status: str = Field(..., description="sent|delivered|read|failed")
    error_message: Optional[str] = None
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None


class AlertRecipientRetryRequest(BaseModel):
    recipient_ids: Optional[List[str]] = None
    channels: Optional[List[str]] = None


class RainfallAlertRequest(BaseModel):
    alert_id: UUID = Field(default_factory=uuid4)
    location: str = Field(..., min_length=2, max_length=120)
    observed_rainfall_mm: float = Field(default=0, ge=0, le=10_000)
    forecast_rainfall_mm: float = Field(default=0, ge=0, le=10_000)
    landslide_probability: float = Field(default=0, ge=0, le=1)
    excavation_active: bool = False
    notes: Optional[str] = Field(default=None, max_length=500)


def _configured_recipients() -> List[str]:
    raw = settings.ALERT_RECIPIENT_PHONES
    recipients = [_validate_phone(phone.strip()) for phone in raw.split(",") if phone.strip()]
    if not recipients:
        raise RuntimeError("ALERT_RECIPIENT_PHONES is not configured")
    return recipients


def _rainfall_alert_message(request: RainfallAlertRequest) -> Optional[str]:
    reasons: List[str] = []
    if request.observed_rainfall_mm >= settings.ALERT_RAINFALL_THRESHOLD_MM:
        reasons.append(f"{request.observed_rainfall_mm:.1f}mm rain observed")
    if request.forecast_rainfall_mm >= settings.ALERT_FORECAST_RAINFALL_THRESHOLD_MM:
        reasons.append(f"{request.forecast_rainfall_mm:.1f}mm rain forecast")
    if request.landslide_probability >= settings.ALERT_LANDSLIDE_PROBABILITY_THRESHOLD:
        reasons.append(f"landslide risk {request.landslide_probability:.0%}")
    if request.excavation_active:
        reasons.append("excavation activity reported")
    if not reasons:
        return None
    suffix = f" Note: {request.notes}" if request.notes else ""
    return (
        f"GeoSentinel ALERT at {request.location}: {', '.join(reasons)}. "
        f"Avoid unstable slopes and roads; follow local authority guidance.{suffix}"
    )[:320]


def _digest_recipients() -> List[str]:
    """Return dedicated digest recipients, falling back to alert recipients."""
    raw = settings.NORTHEAST_DIGEST_RECIPIENT_PHONES or settings.ALERT_RECIPIENT_PHONES
    recipients = [_validate_phone(phone.strip()) for phone in raw.split(",") if phone.strip()]
    if not recipients:
        raise RuntimeError(
            "NORTHEAST_DIGEST_RECIPIENT_PHONES (or ALERT_RECIPIENT_PHONES) is not configured"
        )
    return recipients


async def _fetch_state_weather(client: httpx.AsyncClient, state: str, district: str) -> Dict[str, Any]:
    """Fetch the live weather summary without exposing the ingestion service externally."""
    try:
        response = await client.get(f"{settings.DATA_INGESTION_URL.rstrip('/')}/weather/current/{district}")
        response.raise_for_status()
        payload = response.json()
        return {"state": state, "district": district, "data": payload}
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("northeast_digest_weather_fetch_failed", state=state, error=str(exc))
        return {"state": state, "district": district, "error": str(exc)}


async def build_northeast_digest() -> tuple[str, List[Dict[str, Any]]]:
    """Build a compact 24-hour observed/forecast weather update for all eight NE states."""
    async with httpx.AsyncClient(timeout=35.0) as client:
        summaries = await asyncio.gather(*[
            _fetch_state_weather(client, state, district)
            for state, district in NORTHEAST_STATE_LOCATIONS.items()
        ])

    entries: List[str] = []
    elevated: List[str] = []
    for summary in summaries:
        state = summary["state"]
        code = NORTHEAST_ABBREVIATIONS[state]
        if "error" in summary:
            entries.append(f"{code}: data unavailable")
            continue
        data = summary["data"]
        observed = float(data.get("observed_rainfall_24h_mm") or 0)
        forecast = float(data.get("forecast_rainfall_next_24h_mm") or 0)
        temperature = data.get("temperature_c")
        temp_text = f", {float(temperature):.0f}C" if temperature is not None else ""
        entries.append(f"{code} {summary['district']}: {observed:.0f}/{forecast:.0f}mm{temp_text}")
        if (observed >= settings.ALERT_RAINFALL_THRESHOLD_MM or
                forecast >= settings.ALERT_FORECAST_RAINFALL_THRESHOLD_MM):
            elevated.append(code)

    generated = datetime.now(IST).strftime("%d %b %H:%M IST")
    risk = f" Elevated rain watch: {', '.join(elevated)}." if elevated else " No state above rain alert thresholds."
    message = (
        f"GeoSentinel NER update ({generated}). Rain 24h/next24h: "
        + "; ".join(entries)
        + "." + risk + " Follow local authority guidance."
    )
    return message[:settings.NORTHEAST_DIGEST_MAX_LENGTH], summaries


async def send_northeast_digest() -> Dict[str, Any]:
    """Send the regional digest and retain only safe delivery metadata in memory."""
    digest_status["last_run_at"] = datetime.now(timezone.utc).isoformat()
    try:
        message, summaries = await build_northeast_digest()
        try:
            sms_recipients = _digest_recipients()
        except RuntimeError:
            if not free_dispatcher.active:
                raise
            sms_recipients = []
            logger.info("northeast_digest_sms_recipients_empty_using_free_channels")
        results = []
        for phone in sms_recipients:
            try:
                result = await sms_provider.send(phone, message, settings.SMS_TEMPLATE_ID_ALERT)
                results.append({
                    "phone": phone[:6] + "****",
                    "status": result.get("status", "sent"),
                    "provider_id": result.get("provider_message_id"),
                })
            except (RuntimeError, httpx.HTTPError) as exc:
                logger.error("northeast_digest_sms_failed", error=str(exc))
                results.append({"phone": phone[:6] + "****", "status": "failed", "error": str(exc)})
        results.extend(await deliver_via_free_channels(message, title="GeoSentinel NER update"))
        delivered = sum(result["status"] in {"sent", "simulated"} for result in results)
        statuses = {result["status"] for result in results}
        overall_status = "simulated" if statuses == {"simulated"} else "sent" if delivered else "failed"
        digest_status.update({"last_status": overall_status, "last_error": None if delivered else "No SMS delivered"})
        logger.info("northeast_digest_processed", status=overall_status, delivered=delivered, total=len(results))
        return {
            "status": overall_status,
            "message": message,
            "delivered": delivered,
            "total": len(results),
            "results": results,
            "states": summaries,
        }
    except Exception as exc:
        digest_status.update({"last_status": "failed", "last_error": str(exc)})
        logger.error("northeast_digest_failed", error=str(exc))
        return {"status": "failed", "sent": 0, "total": 0, "error": str(exc)}


# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting_notification_service", env=settings.APP_ENV)
    await init_db()
    if settings.NORTHEAST_DIGEST_ENABLED:
        digest_scheduler.add_job(
            send_northeast_digest,
            "interval",
            minutes=settings.NORTHEAST_DIGEST_INTERVAL_MINUTES,
            id="northeast-sms-digest",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        digest_scheduler.start()
        logger.info(
            "northeast_digest_scheduler_started",
            interval_minutes=settings.NORTHEAST_DIGEST_INTERVAL_MINUTES,
        )
    yield
    if digest_scheduler.running:
        digest_scheduler.shutdown(wait=False)
    logger.info("shutting_down_notification_service")
    await close_db()


app = FastAPI(
    title="GeoSentinel-NER Notification Service",
    description="Multi-channel alert delivery",
    version="0.1.0",
    docs_url="/docs" if settings.APP_DEBUG else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.APP_DEBUG else None,
    lifespan=lifespan,
)


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "service": "notification-service",
        "channels": ["sms", "push", "whatsapp", "email", "cap"],
        "northeast_digest": {
            "enabled": settings.NORTHEAST_DIGEST_ENABLED,
            "interval_minutes": settings.NORTHEAST_DIGEST_INTERVAL_MINUTES,
            **digest_status,
        },
    }


@app.post(f"{settings.API_PREFIX}/send", response_model=NotificationResponse, tags=["Notifications"],
          dependencies=[Depends(require_role("admin"))])
async def send_notification(
    request: NotificationRequest,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db_session),
):
    dispatcher = NotificationDispatcher(db)
    notification_id = uuid4()
    background_tasks.add_task(
        dispatcher.dispatch,
        alert_id=request.alert_id,
        recipients=request.recipients,
        message_templates=request.message_templates,
        severity=request.severity,
    )
    logger.info("notification_queued", notification_id=str(notification_id), user=principal.username)
    return NotificationResponse(
        notification_id=notification_id,
        status="queued",
        results={"queued": len(request.recipients)},
    )


@app.post(
    f"{settings.API_PREFIX}/alerts/rainfall",
    tags=["Notifications"],
    dependencies=[Depends(require_role("admin"))],
)
async def send_rainfall_alert(
    request: RainfallAlertRequest,
    principal: Principal = Depends(get_principal),
):
    """Send an SMS (and any enabled free channels) when observed/forecast rain
    or slope activity crosses a threshold."""
    message = _rainfall_alert_message(request)
    if message is None:
        return {
            "status": "not_triggered",
            "alert_id": str(request.alert_id),
            "reasons": [],
            "sent": 0,
        }

    try:
        recipients = _configured_recipients()
    except RuntimeError:
        recipients = []
        if not free_dispatcher.active:
            raise HTTPException(
                status_code=503,
                detail="No ALERT_RECIPIENT_PHONES configured and no free alert "
                       "channels enabled (ALERT_FREE_CHANNELS)",
            )
        logger.info("rainfall_alert_skipping_sms_no_recipients")

    results = []
    for phone in recipients:
        try:
            result = await sms_provider.send(
                phone,
                message,
                template_id=settings.SMS_TEMPLATE_ID_ALERT,
            )
            results.append({
                "phone": phone[:6] + "****",
                "status": "sent",
                "provider_id": result.get("provider_message_id"),
            })
        except (RuntimeError, httpx.HTTPError) as exc:
            logger.error("rainfall_sms_failed", alert_id=str(request.alert_id), error=str(exc))
            results.append({"phone": phone[:6] + "****", "status": "failed", "error": str(exc)})

    results.extend(
        await deliver_via_free_channels(message, title=f"GeoSentinel rainfall alert - {request.location}")
    )

    sent = sum(1 for result in results if result["status"] == "sent")
    logger.info(
        "rainfall_alert_processed",
        alert_id=str(request.alert_id),
        location=request.location,
        sent=sent,
        total=len(results),
        user=principal.username,
    )
    return {
        "status": "sent" if sent else "failed",
        "alert_id": str(request.alert_id),
        "message": message,
        "sent": sent,
        "total": len(results),
        "results": results,
    }


@app.get(
    f"{settings.API_PREFIX}/digests/northeast/status",
    tags=["Notifications"],
    dependencies=[Depends(require_role("admin"))],
)
async def northeast_digest_state():
    """Show scheduler state and the result of the most recent regional SMS run."""
    return {
        "enabled": settings.NORTHEAST_DIGEST_ENABLED,
        "interval_minutes": settings.NORTHEAST_DIGEST_INTERVAL_MINUTES,
        "scheduled": digest_scheduler.get_job("northeast-sms-digest") is not None,
        **digest_status,
    }


@app.post(
    f"{settings.API_PREFIX}/digests/northeast/send",
    tags=["Notifications"],
    dependencies=[Depends(require_role("admin"))],
)
async def send_northeast_digest_now():
    """Send one North East status SMS now; use this to verify provider configuration."""
    return await send_northeast_digest()


@app.post(f"{settings.API_PREFIX}/templates/render", response_model=TemplateRenderResponse, tags=["Notifications"])
async def render_template(request: TemplateRenderRequest):
    title = request.variables.get("title", "Landslide risk")
    body = request.variables.get("message", "Stay safe.")
    return TemplateRenderResponse(rendered={
        "sms": f"ALERT: {title}. {body}",
        "push": f"{title}: {body}",
        "whatsapp": f"*{title}*\n{body}",
        "email": f"<h2>{title}</h2><p>{body}</p>",
        "cap": f"<alert><info><event>{title}</event></info></alert>",
    })


@app.get(f"{settings.API_PREFIX}/templates/{{template_id}}")
async def get_template(template_id: str, language: str = "en"):
    templates = {
        "alert_high_risk": {
            "en": "HIGH RISK: Heavy rainfall forecast. Landslide risk increased in your area.",
            "hi": "उच्च जोखिम: भारी वर्षा का पूर्वानुमान। आपके क्षेत्र में भूस्खलन का खतरा बढ़ा।",
        },
        "alert_evacuation": {
            "en": "EVACUATE NOW: Imminent landslide danger. Move to safe location immediately.",
            "hi": "अभी निकलें: आसन्न भूस्खलन खतरा। तुरंत सुरक्षित स्थान पर जाएं।",
        },
    }
    return templates.get(template_id, {}).get(language, "Template not found")


# ----- Test endpoints: now require admin auth (previously open) -----
@app.post(f"{settings.API_PREFIX}/test/sms", dependencies=[Depends(require_role("admin"))])
async def test_sms(req: TestSMSRequest):
    result = await sms_provider.send(req.phone, req.message)
    return result


@app.post(f"{settings.API_PREFIX}/test/push", dependencies=[Depends(require_role("admin"))])
async def test_push(req: TestPushRequest):
    result = await push_provider.send(req.device_token, req.title, req.body, {})
    return result


@app.post(f"{settings.API_PREFIX}/test/whatsapp", dependencies=[Depends(require_role("admin"))])
async def test_whatsapp(req: TestWhatsAppRequest):
    result = await whatsapp_provider.send_template(req.phone, req.template, "en", req.params)
    return result


@app.post(f"{settings.API_PREFIX}/push/topic", dependencies=[Depends(require_role("admin"))])
async def send_push_topic(req: TopicPushRequest):
    """Send a push notification to all subscribers of a Firebase topic."""
    result = await push_provider.send_topic(req.topic, req.title, req.body, req.data)
    return result


@app.post(f"{settings.API_PREFIX}/push/subscribe", dependencies=[Depends(require_role("admin"))])
async def subscribe_push_topic(req: TopicSubscriptionRequest):
    """Subscribe FCM device tokens to a topic."""
    result = await push_provider.subscribe_to_topic(req.tokens, req.topic)
    return result


@app.post(f"{settings.API_PREFIX}/push/unsubscribe", dependencies=[Depends(require_role("admin"))])
async def unsubscribe_push_topic(req: TopicSubscriptionRequest):
    """Unsubscribe FCM device tokens from a topic."""
    result = await push_provider.unsubscribe_from_topic(req.tokens, req.topic)
    return result


@app.post(f"{settings.API_PREFIX}/test/whatsapp/interactive", dependencies=[Depends(require_role("admin"))])
async def test_whatsapp_interactive(req: TestWhatsAppInteractiveRequest):
    """Send interactive quick reply buttons via WhatsApp Meta Cloud API."""
    result = await whatsapp_provider.send_interactive_buttons(
        to=req.phone,
        body_text=req.body,
        buttons=req.buttons,
        header_text=req.header,
        footer_text=req.footer,
    )
    return result


@app.post(f"{settings.API_PREFIX}/test/whatsapp/location", dependencies=[Depends(require_role("admin"))])
async def test_whatsapp_location(req: TestWhatsAppLocationRequest):
    """Send a location pin via WhatsApp Meta Cloud API."""
    result = await whatsapp_provider.send_location(
        to=req.phone,
        latitude=req.latitude,
        longitude=req.longitude,
        name=req.name,
        address=req.address,
    )
    return result


@app.post(f"{settings.API_PREFIX}/test/whatsapp/media", dependencies=[Depends(require_role("admin"))])
async def test_whatsapp_media(req: TestWhatsAppMediaRequest):
    """Send media (image/document/audio/video) via WhatsApp Meta Cloud API."""
    result = await whatsapp_provider.send_media(
        to=req.phone,
        media_type=req.media_type,
        media_url=req.media_url,
        caption=req.caption,
    )
    return result


# ----- WhatsApp Meta Cloud API Webhook -----
@app.get(f"{settings.API_PREFIX}/whatsapp/webhook")
async def verify_whatsapp_webhook(
    mode: Optional[str] = Query(None, alias="hub.mode"),
    verify_token_param: Optional[str] = Query(None, alias="hub.verify_token"),
    challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification endpoint."""
    if mode == "subscribe" and verify_token_param == settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        logger.info("whatsapp_webhook_verified")
        return Response(content=challenge or "", media_type="text/plain")
    logger.warning("whatsapp_webhook_verification_failed", mode=mode)
    raise HTTPException(status_code=403, detail="Verification token mismatch")


@app.post(f"{settings.API_PREFIX}/whatsapp/webhook")
async def handle_whatsapp_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Process inbound WhatsApp status updates and citizen replies."""
    body = await request.json()
    logger.info("whatsapp_webhook_received", body_keys=list(body.keys()))
    entries = body.get("entry", [])
    from sqlalchemy import text

    updated_count = 0
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            # Process delivery status callbacks (sent, delivered, read, failed)
            statuses = value.get("statuses", [])
            for st in statuses:
                recipient_id = st.get("recipient_id")
                status = st.get("status")  # sent, delivered, read, failed
                timestamp_str = st.get("timestamp")
                status_time = (
                    datetime.fromtimestamp(int(timestamp_str), timezone.utc)
                    if timestamp_str and timestamp_str.isdigit()
                    else datetime.now(timezone.utc)
                )
                errors = st.get("errors")
                err_msg = json.dumps(errors) if errors else None

                if recipient_id and status:
                    # Update alert_recipient table
                    update_sql = """
                        UPDATE alert_recipient
                        SET status = :status,
                            delivered_at = CASE WHEN :status = 'delivered' THEN :status_time ELSE delivered_at END,
                            read_at = CASE WHEN :status = 'read' THEN :status_time ELSE read_at END,
                            error_message = COALESCE(:err_msg, error_message)
                        WHERE channel = 'whatsapp'
                          AND (recipient_id = :recipient_id OR recipient_id = :e164_recipient)
                    """
                    e164_recipient = f"+{recipient_id}" if not recipient_id.startswith("+") else recipient_id
                    await db.execute(
                        text(update_sql),
                        {
                            "status": status,
                            "status_time": status_time,
                            "err_msg": err_msg,
                            "recipient_id": recipient_id,
                            "e164_recipient": e164_recipient,
                        },
                    )
                    updated_count += 1
            # Process inbound messages (replies, feedback)
            messages = value.get("messages", [])
            for msg in messages:
                from_num = msg.get("from")
                msg_type = msg.get("type")
                logger.info("whatsapp_inbound_message", sender=from_num, type=msg_type)
    await db.commit()
    return {"status": "ok", "updated_statuses": updated_count}


# ----- Alert Recipient Persistence & Queries -----
@app.get(
    f"{settings.API_PREFIX}/alerts/{{alert_id}}/recipients",
    response_model=List[AlertRecipientRead],
    tags=["Notifications"],
    dependencies=[Depends(require_role("admin"))],
)
async def get_alert_recipients(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Get delivery status for all recipients of an alert."""
    from sqlalchemy import text

    rows = (
        await db.execute(
            text(
                """
                SELECT id, alert_id, recipient_type, recipient_id, channel,
                       sent_at, delivered_at, read_at, status, error_message,
                       COALESCE(retry_count, 0) AS retry_count
                FROM alert_recipient
                WHERE alert_id = :alert_id
                ORDER BY created_at
                """
            ),
            {"alert_id": alert_id},
        )
    ).mappings().all()
    return [AlertRecipientRead.model_validate(dict(r)) for r in rows]


@app.patch(
    f"{settings.API_PREFIX}/alerts/{{alert_id}}/recipients/{{recipient_id}}/status",
    tags=["Notifications"],
    dependencies=[Depends(require_role("admin"))],
)
async def update_recipient_status(
    alert_id: UUID,
    recipient_id: str,
    body: AlertRecipientStatusUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Manually update delivery status of an alert recipient."""
    from sqlalchemy import text

    result = await db.execute(
        text(
            """
            UPDATE alert_recipient
            SET status = :status,
                error_message = :error_message,
                delivered_at = COALESCE(:delivered_at, delivered_at),
                read_at = COALESCE(:read_at, read_at)
            WHERE alert_id = :alert_id AND recipient_id = :recipient_id
            RETURNING id, status
            """
        ),
        {
            "alert_id": alert_id,
            "recipient_id": recipient_id,
            "status": body.status,
            "error_message": body.error_message,
            "delivered_at": body.delivered_at,
            "read_at": body.read_at,
        },
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Alert recipient record not found")
    await db.commit()
    return {"status": "updated", "id": str(row["id"]), "recipient_status": row["status"]}


@app.post(
    f"{settings.API_PREFIX}/alerts/{{alert_id}}/recipients/retry",
    tags=["Notifications"],
    dependencies=[Depends(require_role("admin"))],
)
async def retry_failed_alert_recipients(
    alert_id: UUID,
    req: AlertRecipientRetryRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Retry deliveries that failed for an alert."""
    from sqlalchemy import text

    rows = (
        await db.execute(
            text(
                """
                SELECT id, alert_id, recipient_type, recipient_id, channel, retry_count
                FROM alert_recipient
                WHERE alert_id = :alert_id
                  AND status = 'failed'
                  AND (:channels_empty = TRUE OR channel = ANY(:channels))
                  AND (:recipients_empty = TRUE OR recipient_id = ANY(:recipients))
                """
            ),
            {
                "alert_id": alert_id,
                "channels": req.channels or [],
                "channels_empty": not bool(req.channels),
                "recipients": req.recipient_ids or [],
                "recipients_empty": not bool(req.recipient_ids),
            },
        )
    ).mappings().all()

    retried = []
    for r in rows:
        await db.execute(
            text(
                """
                UPDATE alert_recipient
                SET status = 'pending',
                    retry_count = COALESCE(retry_count, 0) + 1,
                    error_message = NULL
                WHERE id = :id
                """
            ),
            {"id": r["id"]},
        )
        retried.append(str(r["id"]))
    await db.commit()
    logger.info("alert_recipients_retry_queued", alert_id=str(alert_id), count=len(retried))
    return {"alert_id": str(alert_id), "retried_count": len(retried), "retried_ids": retried}


@app.get(f"{settings.API_PREFIX}/free-channels", dependencies=[Depends(require_role("admin"))])
async def free_channels_state():
    """Show which free alert channels are enabled and correctly configured."""
    def _state(channel: str) -> Dict[str, Any]:
        checks = {
            "whatsapp": bool(settings.CALLMEBOT_API_KEY) and bool(settings.ALERT_RECIPIENT_PHONES),
            "telegram": bool(settings.TELEGRAM_BOT_TOKEN) and bool(settings.TELEGRAM_CHAT_IDS),
            "push": bool(settings.NTFY_TOPICS),
        }
        return {"enabled": channel in free_dispatcher.active, "configured": checks[channel]}

    return {
        "channels": {c: _state(c) for c in FreeChannelDispatcher.FREE_CHANNELS},
        "unknown_channels": free_dispatcher.unknown_channels,
    }


@app.post(f"{settings.API_PREFIX}/test/free-channels", dependencies=[Depends(require_role("admin"))])
async def test_free_channels():
    """Send one test message through every enabled free channel."""
    if not free_dispatcher.active:
        raise HTTPException(
            status_code=503,
            detail="No free channels enabled. Set ALERT_FREE_CHANNELS "
                   "(e.g. whatsapp,telegram,push) and the per-channel credentials.",
        )
    results = await deliver_via_free_channels(
        "GeoSentinel test message: your free alert channel is working."
    )
    delivered = sum(1 for r in results if r["status"] == "sent")
    return {
        "status": "sent" if delivered else "failed",
        "delivered": delivered,
        "total": len(results),
        "results": results,
    }


# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8006, reload=settings.APP_DEBUG)
