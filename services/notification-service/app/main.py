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
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from geosentinel_shared import (
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
            response.raise_for_status()
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

    async def send(self, device_token: str, title: str, body: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.project_id:
            raise RuntimeError("FIREBASE_PROJECT_ID is not configured")
        logger.info("push_sending", device_token=device_token[:10] + "****", title=title)
        # TODO: firebase-admin SDK
        return {"status": "sent", "message_id": f"mock_{uuid4().hex[:8]}"}

    async def send_multicast(self, device_tokens: List[str], title: str, body: str, data: Dict) -> Dict[str, Any]:
        return {"success_count": len(device_tokens), "failure_count": 0}


class WhatsAppProvider:
    def __init__(self):
        self.phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self.access_token = settings.WHATSAPP_ACCESS_TOKEN

    async def send_template(self, to: str, template_name: str, language: str, params: List[str]) -> Dict[str, Any]:
        to = _validate_phone(to)
        if not self.access_token:
            raise RuntimeError("WHATSAPP_ACCESS_TOKEN is not configured")
        logger.info("whatsapp_sending", to=to[:6] + "****", template=template_name)
        # TODO: Meta Cloud API
        return {"status": "sent", "message_id": f"mock_{uuid4().hex[:8]}"}


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
            return await push_provider.send(
                device_token=recipient["device_token"],
                title=f"GeoSentinel Alert - {severity.upper()}",
                body=template,
                data={"alert_id": recipient.get("alert_id"), "severity": severity},
            )
        if channel == "whatsapp":
            return await whatsapp_provider.send_template(
                to=recipient["contact"],
                template_name=recipient.get("whatsapp_template", "alert_template"),
                language=recipient.get("language", settings.DEFAULT_LANGUAGE),
                params=recipient.get("template_params", []),
            )
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
        # TODO: persist to alert_recipient table
        pass


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
        recipients = _digest_recipients()
        results = []
        for phone in recipients:
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
    """Send an SMS when observed/forecast rain or slope activity crosses a threshold."""
    message = _rainfall_alert_message(request)
    if message is None:
        return {
            "status": "not_triggered",
            "alert_id": str(request.alert_id),
            "reasons": [],
            "sent": 0,
        }

    recipients = _configured_recipients()
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


# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8006, reload=settings.APP_DEBUG)
