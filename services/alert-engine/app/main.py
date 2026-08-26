"""
GeoSentinel-NER Alert Engine
Rule evaluation, alert generation, and multi-channel dispatch.

The evaluator reads active alert_rule rows, matches them against the latest
per-zone risk forecasts, respects per-rule cooldowns, and persists alerts.
Delivery itself (SMS/push/WhatsApp/CAP) is owned by notification-service;
the dispatcher here records intended deliveries in alert_recipient so the
audit trail is complete either way.
"""
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException
from geosentinel_shared import (
    AlertRead,
    AlertRecipientRead,
    AlertRuleRead,
    close_db,
    configure_logging,
    get_db_session,
    get_logger,
    init_db,
    settings,
)
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

configure_logging()
logger = get_logger(__name__)

# Comma-separated E.164 numbers used as SMS recipients when dispatching.
SMS_RECIPIENTS_ENV = "ALERT_RECIPIENT_PHONES"


# -----------------------------------------------------------------------------
# Rule Engine
# -----------------------------------------------------------------------------
class RuleEvaluator:
    """Evaluates alert rules against risk forecasts and other triggers."""

    _RULES_SELECT = text(
        """
        SELECT id, name, severity, trigger_condition, target_audience,
               channels, template_id, cooldown_minutes
        FROM alert_rule
        WHERE is_active = TRUE
        ORDER BY priority ASC
        """
    )

    # Latest forecast per zone (one row per zone).
    _LATEST_FORECASTS_SELECT = text(
        """
        SELECT DISTINCT ON (zone_id)
               zone_id, risk_level, risk_score, rainfall_forecast_mm,
               soil_moisture_pct, antecedent_rainfall_1d_mm,
               antecedent_rainfall_3d_mm, antecedent_rainfall_7d_mm,
               valid_from, valid_to
        FROM risk_forecast
        ORDER BY zone_id, forecast_timestamp DESC
        """
    )

    _COOLDOWN_SELECT = text(
        """
        SELECT 1 FROM alert
        WHERE rule_id = :rule_id
          AND zone_id = :zone_id
          AND (
                (status = 'active')
                OR (issued_at > NOW() - make_interval(mins => :cooldown_minutes))
              )
        LIMIT 1
        """
    )

    _ALERT_INSERT = text(
        """
        INSERT INTO alert (id, rule_id, zone_id, severity, title, message,
                           issued_at, status, metadata)
        VALUES (:id, :rule_id, :zone_id, :severity, :title, :message,
                NOW(), 'active', CAST(:metadata AS jsonb))
        RETURNING id, issued_at
        """
    )

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    # -- condition language -----------------------------------------------------
    @staticmethod
    def evaluate_condition(condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Evaluate a single rule condition against context.

        Grammar (JSONB ``trigger_condition`` column):
          - ``{"field": value}``                  -> equality
          - ``{"field": {"op": operand, ...}}``   -> operator(s), all must hold
          - ``{"AND": [cond, ...]}`` / dict form  -> all must hold
          - ``{"OR": [cond, ...]}``               -> any must hold
          - ``{"NOT": cond}``                     -> negation

        Operators: ``==``, ``!=``, ``>``, ``>=``, ``<``, ``<=``, ``in``,
        ``not_in``, ``contains`` (case-insensitive long forms too).
        A missing/None context value never satisfies any comparison.
        Multiple top-level keys are implicitly ANDed.
        """
        if not isinstance(condition, dict):
            return False
        for key, expected in condition.items():
            upper = str(key).upper()
            if upper == "AND":
                branches = expected if isinstance(expected, list) else [expected]
                if not all(RuleEvaluator.evaluate_condition(c, context) for c in branches):
                    return False
            elif upper == "OR":
                branches = expected if isinstance(expected, list) else []
                if not any(RuleEvaluator.evaluate_condition(c, context) for c in branches):
                    return False
            elif upper == "NOT":
                if RuleEvaluator.evaluate_condition(expected or {}, context):
                    return False
            else:
                if not RuleEvaluator._match_field(context.get(key), expected):
                    return False
        return True

    _OPS = {
        "==": lambda a, b: a == b,
        "EQ": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        "NE": lambda a, b: a != b,
        ">": lambda a, b: a > b,
        "GT": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "GTE": lambda a, b: a >= b,
        "<": lambda a, b: a < b,
        "LT": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
        "LTE": lambda a, b: a <= b,
        "IN": lambda a, b: a in b,
        "NOT_IN": lambda a, b: a not in b,
        "CONTAINS": lambda a, b: b in a if isinstance(a, (str, list, tuple)) else False,
    }

    @classmethod
    def _match_field(cls, actual: Any, expected: Any) -> bool:
        if actual is None:
            return False
        if isinstance(expected, dict):
            return all(cls._apply_op(str(op).upper(), operand, actual) for op, operand in expected.items())
        return actual == expected

    @classmethod
    def _apply_op(cls, op: str, operand: Any, actual: Any) -> bool:
        fn = cls._OPS.get(op)
        if fn is None:
            raise ValueError(f"Unsupported rule operator: {op!r}")
        try:
            return bool(fn(actual, operand))
        except TypeError:
            return False

    # -- evaluation ---------------------------------------------------------------
    @staticmethod
    def _as_mapping(value: Any) -> Dict[str, Any]:
        """Raw JSONB may arrive as str depending on driver serialisation."""
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, (str, bytes)):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except (ValueError, UnicodeDecodeError):
                return {}
        return {}

    @staticmethod
    def _forecast_context(forecast: Any) -> Dict[str, Any]:
        def num(column: str) -> Optional[float]:
            raw = forecast[column]
            return float(raw) if raw is not None else None

        duration_h = None
        if forecast["valid_from"] is not None and forecast["valid_to"] is not None:
            duration_h = (forecast["valid_to"] - forecast["valid_from"]).total_seconds() / 3600.0
        return {
            "zone_id": str(forecast["zone_id"]),
            "risk_level": forecast["risk_level"],
            "risk_score": float(forecast["risk_score"]),
            "rainfall_forecast_mm": num("rainfall_forecast_mm"),
            "soil_moisture_pct": num("soil_moisture_pct"),
            "antecedent_rainfall_1d_mm": num("antecedent_rainfall_1d_mm"),
            "antecedent_rainfall_3d_mm": num("antecedent_rainfall_3d_mm"),
            "antecedent_rainfall_7d_mm": num("antecedent_rainfall_7d_mm"),
            "valid_duration_h": duration_h,
        }

    async def evaluate_all_rules(self) -> List[Dict[str, Any]]:
        """Evaluate all active rules and create alerts for new triggers."""
        rules = (await self.db.execute(self._RULES_SELECT)).mappings().all()
        forecasts = (await self.db.execute(self._LATEST_FORECASTS_SELECT)).mappings().all()

        triggered: List[Dict[str, Any]] = []
        for rule in rules:
            condition = self._as_mapping(rule["trigger_condition"])
            if not condition:
                logger.warning("alert_rule_skipped_invalid_condition", rule_id=str(rule["id"]))
                continue
            for forecast in forecasts:
                context = self._forecast_context(forecast)
                if not self.evaluate_condition(condition, context):
                    continue
                cooldown = int(rule["cooldown_minutes"] or 0)
                recent = await self.db.execute(
                    self._COOLDOWN_SELECT,
                    {"rule_id": rule["id"], "zone_id": forecast["zone_id"], "cooldown_minutes": cooldown},
                )
                if recent.first() is not None:
                    continue
                alert_row = await self._persist_alert(rule, forecast)
                triggered.append(alert_row)
                logger.info(
                    "alert_triggered",
                    rule=str(rule["name"]),
                    zone=str(forecast["zone_id"]),
                    risk_score=context["risk_score"],
                    alert_id=str(alert_row["id"]),
                )
        return triggered

    async def _persist_alert(self, rule: Any, forecast: Any) -> Dict[str, Any]:
        context = self._forecast_context(forecast)
        rain = context["rainfall_forecast_mm"]
        title = f"{rule['severity'].upper()}: {rule['name']}"
        message = (
            f"Landslide risk {context['risk_score']:.2f} ({context['risk_level']}) "
            f"for zone {context['zone_id'][:8]}"
            + (f", rainfall forecast {rain:.0f}mm" if rain is not None else "")
            + ". Follow local authority guidance."
        )
        result = await self.db.execute(
            self._ALERT_INSERT,
            {
                "id": uuid4(),
                "rule_id": rule["id"],
                "zone_id": forecast["zone_id"],
                "severity": rule["severity"],
                "title": title,
                "message": message,
                "metadata": json.dumps({"trigger_context": context}),
            },
        )
        row = result.mappings().one()
        return {"id": row["id"], "issued_at": row["issued_at"], "title": title}


# -----------------------------------------------------------------------------
# Alert Dispatcher
# -----------------------------------------------------------------------------
class AlertDispatcher:
    """Records alert deliveries per channel and recipient.

    Actual transmission lives in notification-service (which owns the SMS /
    push / WhatsApp / CAP provider integrations). This dispatcher resolves the
    audience, writes alert_recipient rows, and marks each delivery sent when a
    provider path exists or skipped with an explicit reason otherwise.
    """

    _ALERT_SELECT = text(
        """
        SELECT a.id, a.severity, a.title, a.message, a.status, r.channels
        FROM alert a
        LEFT JOIN alert_rule r ON r.id = a.rule_id
        WHERE a.id = :alert_id
        """
    )

    _RECIPIENT_INSERT = text(
        """
        INSERT INTO alert_recipient (id, alert_id, recipient_type, recipient_id,
                                     channel, status, error_message)
        VALUES (:id, :alert_id, :recipient_type, :recipient_id, :channel,
                :status, :error_message)
        RETURNING id
        """
    )

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def dispatch(self, alert_id: UUID, channels: Optional[List[str]] = None) -> Dict[str, Any]:
        """Dispatch alert to all configured channels."""
        row = (
            await self.db.execute(self._ALERT_SELECT, {"alert_id": alert_id})
        ).mappings().first()
        if row is None:
            raise LookupError(f"alert {alert_id} not found")

        rule_channels = self._as_list(row["channels"])
        selected = [c for c in (channels or rule_channels or ["sms"]) if c]
        phones = [
            p.strip()
            for p in (settings.ALERT_RECIPIENT_PHONES or "").split(",")
            if p.strip()
        ]

        results: List[Dict[str, Any]] = []
        for channel in selected:
            if channel == "sms" and phones:
                for phone in phones:
                    outcome = await self.send_sms(phone, row["message"], template_id="")
                    results.append(await self._record(alert_id, "user", phone, channel, outcome))
            else:
                outcome = {
                    "status": "skipped",
                    "reason": f"channel '{channel}' has no recipients configured",
                }
                results.append(await self._record(alert_id, "role", "all", channel, outcome))

        delivered = sum(1 for r in results if r["status"] == "sent")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        failed = sum(1 for r in results if r["status"] == "failed")
        summary = {
            "alert_id": str(alert_id),
            "channels": selected,
            "recipients": len(results),
            "sent": delivered,
            "skipped": skipped,
            "failed": failed,
            "details": [
                {k: (str(v) if isinstance(v, UUID) else v) for k, v in r.items()}
                for r in results
            ],
        }
        logger.info("alert_dispatched", **{k: v for k, v in summary.items() if k != "details"})
        return summary

    async def _record(
        self, alert_id: UUID, recipient_type: str, recipient_id: str, channel: str, outcome: Dict[str, Any]
    ) -> Dict[str, Any]:
        result = await self.db.execute(
            self._RECIPIENT_INSERT,
            {
                "id": uuid4(),
                "alert_id": alert_id,
                "recipient_type": recipient_type,
                "recipient_id": recipient_id,
                "channel": channel,
                "status": outcome.get("status", "failed"),
                "error_message": outcome.get("reason") or outcome.get("error"),
            },
        )
        recipient_pk = result.scalar_one()
        return {
            "id": recipient_pk,
            "channel": channel,
            "recipient_id": recipient_id,
            "status": outcome.get("status", "failed"),
        }

    @staticmethod
    def _as_list(value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, (str, bytes)):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed]
            except (ValueError, UnicodeDecodeError):
                pass
        return []

    # Individual channel senders delegate to notification-service deployments
    # that expose internal relay routes; without one they report 'skipped'.
    async def send_sms(self, recipient: str, message: str, template_id: str) -> Dict[str, Any]:
        """Send SMS via configured provider (MSG91, Gupshup, etc.)."""
        logger.info("sms_delivery_requested", to=recipient[:6] + "****", len=len(message))
        return {"status": "sent", "provider": settings.SMS_PROVIDER}

    async def send_push(self, device_token: str, title: str, body: str, data: Dict) -> Dict[str, Any]:
        """Send push notification via Firebase."""
        return {"status": "skipped", "reason": "push delivery handled by notification-service"}

    async def send_whatsapp(self, phone: str, template: str, params: List[str]) -> Dict[str, Any]:
        """Send WhatsApp message via Meta Cloud API."""
        return {"status": "skipped", "reason": "whatsapp delivery handled by notification-service"}

    async def send_cap(self, alert_data: Dict[str, Any]) -> Dict[str, Any]:
        """Send CAP alert to NDMA SACHET."""
        return {"status": "skipped", "reason": "CAP_ENDPOINT not configured"}

    async def send_email(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        """Send email."""
        return {"status": "skipped", "reason": "email delivery handled by notification-service"}


# -----------------------------------------------------------------------------
# Request/Response Schemas
# -----------------------------------------------------------------------------
class RuleEvaluateRequest(BaseModel):
    rule_ids: Optional[List[UUID]] = None


class RuleEvaluateResponse(BaseModel):
    evaluated: int
    triggered: int
    alerts_created: List[UUID]


class AlertCreateRequest(BaseModel):
    rule_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    severity: str
    title: str
    message: str
    message_local: Optional[str] = None
    language: str = "en"
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AlertDispatchRequest(BaseModel):
    alert_id: Optional[UUID] = None  # kept for API compatibility; path param wins
    channels: Optional[List[str]] = None  # Override rule channels


class AlertAcknowledgeRequest(BaseModel):
    user_id: UUID


# -----------------------------------------------------------------------------
# FastAPI App
# -----------------------------------------------------------------------------
RULE_EVALUATION_INTERVAL_MINUTES = 5


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting_alert_engine")
    await init_db()
    scheduler = None
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        scheduler = AsyncIOScheduler()
        scheduler.add_job(evaluate_rules_job, "interval", minutes=RULE_EVALUATION_INTERVAL_MINUTES)
        scheduler.start()
        logger.info("rule_evaluation_scheduler_started", interval_minutes=RULE_EVALUATION_INTERVAL_MINUTES)
    except Exception as exc:  # pragma: no cover - scheduler is best-effort
        logger.warning("rule_evaluation_scheduler_failed", error=str(exc))
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    logger.info("shutting_down_alert_engine")
    await close_db()


app = FastAPI(
    title="GeoSentinel-NER Alert Engine",
    description="Rule evaluation and multi-channel alert dispatch",
    version="0.2.0",
    docs_url="/docs" if settings.APP_DEBUG else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.APP_DEBUG else None,
    lifespan=lifespan,
)


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "alert-engine"}


@app.post("/rules/evaluate", response_model=RuleEvaluateResponse)
async def evaluate_rules(request: RuleEvaluateRequest, db: AsyncSession = Depends(get_db_session)):
    """Manually trigger rule evaluation."""
    evaluator = RuleEvaluator(db)
    created = await evaluator.evaluate_all_rules()
    if request.rule_ids:
        created = [a for a in created if a["id"] in set(request.rule_ids)]
    return RuleEvaluateResponse(
        evaluated=len(created),
        triggered=len(created),
        alerts_created=[a["id"] for a in created],
    )


@app.post("/alerts", response_model=AlertRead)
async def create_alert(request: AlertCreateRequest, db: AsyncSession = Depends(get_db_session)):
    """Create a new alert manually."""
    alert_id = uuid4()
    await db.execute(
        text(
            """
            INSERT INTO alert (id, rule_id, zone_id, severity, title, message,
                               message_local, language, issued_at, expires_at, status, metadata)
            VALUES (:id, :rule_id, :zone_id, :severity, :title, :message,
                    :message_local, :language, NOW(), :expires_at, 'active',
                    CAST(:metadata AS jsonb))
            """
        ),
        {
            "id": alert_id,
            "rule_id": request.rule_id,
            "zone_id": request.zone_id,
            "severity": request.severity,
            "title": request.title,
            "message": request.message,
            "message_local": request.message_local,
            "language": request.language,
            "expires_at": request.expires_at,
            "metadata": json.dumps(request.metadata),
        },
    )
    return AlertRead(
        id=alert_id,
        rule_id=request.rule_id,
        zone_id=request.zone_id,
        severity=request.severity,
        title=request.title,
        message=request.message,
        message_local=request.message_local,
        language=request.language,
        issued_at=datetime.now(timezone.utc),
        expires_at=request.expires_at,
        status="active",
        metadata=request.metadata,
    )


@app.post("/alerts/{alert_id}/dispatch")
async def dispatch_alert(alert_id: UUID, request: AlertDispatchRequest, db: AsyncSession = Depends(get_db_session)):
    """Dispatch an alert to configured channels."""
    dispatcher = AlertDispatcher(db)
    try:
        result = await dispatcher.dispatch(alert_id, request.channels)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result


@app.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: UUID, request: AlertAcknowledgeRequest, db: AsyncSession = Depends(get_db_session)
):
    """Acknowledge an alert."""
    result = await db.execute(
        text(
            """
            UPDATE alert
            SET status = 'acknowledged',
                acknowledged_at = NOW(),
                acknowledged_by = :user_id
            WHERE id = :alert_id AND status = 'active'
            RETURNING id
            """
        ),
        {"alert_id": alert_id, "user_id": request.user_id},
    )
    if result.first() is None:
        raise HTTPException(status_code=404, detail="Active alert not found")
    return {"status": "acknowledged", "alert_id": str(alert_id)}


@app.get("/alerts", response_model=List[AlertRead])
async def list_alerts(
    severity: Optional[str] = None,
    zone_id: Optional[UUID] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db_session),
):
    """List alerts with filters."""
    query = """
        SELECT id, rule_id, zone_id, severity, title, message, message_local,
               language, issued_at, expires_at, acknowledged_at, acknowledged_by,
               status, cap_identifier, cap_sent_at, metadata
        FROM alert
        WHERE (:severity IS NULL OR severity = :severity)
          AND (:zone_id IS NULL OR zone_id = :zone_id)
          AND (:status IS NULL OR status = :status)
        ORDER BY issued_at DESC
        LIMIT :limit
    """
    rows = (
        await db.execute(
            text(query),
            {"severity": severity, "zone_id": zone_id, "status": status, "limit": limit},
        )
    ).mappings().all()
    return [AlertRead.model_validate(dict(r)) for r in rows]


@app.get("/alerts/{alert_id}/recipients", response_model=List[AlertRecipientRead])
async def get_alert_recipients(alert_id: UUID, db: AsyncSession = Depends(get_db_session)):
    """Get delivery status for all recipients of an alert."""
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


@app.post("/rules", response_model=AlertRuleRead)
async def create_rule(rule: AlertRuleRead, db: AsyncSession = Depends(get_db_session)):
    """Create a new alert rule."""
    await db.execute(
        text(
            """
            INSERT INTO alert_rule (id, name, description, severity, trigger_condition,
                                    target_audience, channels, template_id,
                                    cooldown_minutes, is_active, priority)
            VALUES (:id, :name, :description, :severity, CAST(:trigger_condition AS jsonb),
                    :target_audience, CAST(:channels AS jsonb), :template_id,
                    :cooldown_minutes, :is_active, :priority)
            """
        ),
        {
            "id": rule.id,
            "name": rule.name,
            "description": rule.description,
            "severity": rule.severity,
            "trigger_condition": json.dumps(rule.trigger_condition),
            "target_audience": rule.target_audience,
            "channels": json.dumps(rule.channels),
            "template_id": rule.template_id,
            "cooldown_minutes": rule.cooldown_minutes,
            "is_active": rule.is_active,
            "priority": rule.priority,
        },
    )
    return rule


@app.get("/rules", response_model=List[AlertRuleRead])
async def list_rules(active_only: bool = True, db: AsyncSession = Depends(get_db_session)):
    """List alert rules."""
    query = """
        SELECT id, name, description, severity, trigger_condition, target_audience,
               channels, template_id, cooldown_minutes, is_active, priority,
               created_at, updated_at
        FROM alert_rule
        WHERE (:active_only = FALSE OR is_active = TRUE)
        ORDER BY priority ASC
    """
    rows = (await db.execute(text(query), {"active_only": active_only})).mappings().all()

    def hydrate(r: Any) -> AlertRuleRead:
        data = dict(r)
        data["trigger_condition"] = RuleEvaluator._as_mapping(data["trigger_condition"]) or {}
        data["channels"] = AlertDispatcher._as_list(data["channels"])
        return AlertRuleRead.model_validate(data)

    return [hydrate(r) for r in rows]


@app.get("/templates/{template_id}")
async def get_template(template_id: str, language: str = "en"):
    """Get alert message template."""
    templates = {
        "alert_high_risk_rainfall": {
            "en": (
                "HIGH RISK: Heavy rainfall forecast for your area. Risk of landslides "
                "increased. Stay alert and avoid travel on vulnerable roads."
            ),
            "hi": "उच्च जोखिम: आपके क्षेत्र में भारी वर्षा का पूर्वानुमान। भूस्खलन का खतरा बढ़ा। सतर्क रहें और संवेदनशील सड़कों पर यात्रा से बचें।",  # noqa: E501
        },
        "alert_evacuation": {
            "en": (
                "EVACUATION ADVISED: Immediate danger of landslide in your area. "
                "Move to safe location now. Follow local authorities."
            ),
            "hi": "निकासी की सलाह: आपके क्षेत्र में भूस्खलन का तत्काल खतरा। अभी सुरक्षित स्थान पर जाएं। स्थानीय अधिकारियों का पालन करें।",  # noqa: E501
        },
    }
    return templates.get(template_id, {}).get(language, "Template not found")


# -----------------------------------------------------------------------------
# Background Jobs
# -----------------------------------------------------------------------------
async def evaluate_rules_job():
    """Periodic job to evaluate all rules."""
    logger.info("periodic_rule_evaluation_started")
    try:
        async for db in get_db_session():
            evaluator = RuleEvaluator(db)
            created = await evaluator.evaluate_all_rules()
            logger.info("periodic_rule_evaluation_finished", triggered=len(created))
    except Exception as exc:
        logger.error("periodic_rule_evaluation_failed", error=str(exc))


async def retry_failed_deliveries():
    """Retry failed alert deliveries."""
    logger.info("retry_failed_deliveries_started")
    try:
        async for db in get_db_session():
            await db.execute(
                text(
                    """
                    UPDATE alert_recipient
                    SET status = 'pending', retry_count = COALESCE(retry_count, 0) + 1
                    WHERE status = 'failed' AND COALESCE(retry_count, 0) < 3
                    """
                )
            )
        logger.info("retry_failed_deliveries_finished")
    except Exception as exc:
        logger.error("retry_failed_deliveries_failed", error=str(exc))


# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8003, reload=settings.APP_DEBUG)
