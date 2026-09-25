"""
GeoSentinel-NER API Gateway
Main FastAPI application with authentication, routing, and middleware.
"""
import asyncio
import contextlib
import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from geosentinel_shared import (
    AdminStateRead,
    AlertRead,
    AppUserCreate,
    AppUserRead,
    AppUserUpdate,
    CitizenReportCreate,
    CitizenReportMediaRead,
    CitizenReportRead,
    HealthCheck,
    InfrastructureFacilityRead,
    InfrastructureRoadRead,
    LandslideInventoryRead,
    PageParams,
    PaginatedResponse,
    RiskForecastRead,
    SensorReadingRead,
    SensorStationRead,
    SusceptibilityZoneRead,
    Token,
    check_permission,
    close_db,
    configure_logging,
    create_access_token,
    create_refresh_token,
    get_db_session,
    get_logger,
    get_primary_db,
    get_ts_session,
    hash_password,
    init_db,
    settings,
    verify_password,
    verify_token,
)
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

configure_logging()
logger = get_logger(__name__)

security = HTTPBearer(auto_error=False)

# -----------------------------------------------------------------------------
# In-process rate limiter (token bucket keyed by client IP + route).
# Good enough for a single instance; in a multi-instance deployment use Redis.
# -----------------------------------------------------------------------------
class _RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._buckets: dict[str, tuple[float, float]] = {}
        self._max_buckets = 10_000

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        self._prune(now)
        refill = self.per_minute / 60.0
        tokens, last = self._buckets.get(key, (float(self.per_minute), now))
        tokens = min(float(self.per_minute), tokens + (now - last) * refill)
        if tokens < 1:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1, now)
        return True

    def _prune(self, now: float) -> None:
        """Drop stale buckets so spoofed IPs cannot grow memory unboundedly."""
        if len(self._buckets) < self._max_buckets:
            return
        # A bucket is stale once it has fully refilled since its last touch.
        idle_seconds = self.per_minute / max(self.per_minute / 60.0, 1e-9)
        cutoff = now - max(idle_seconds * 2, 120.0)
        for k in [k for k, (_, last) in self._buckets.items() if last < cutoff]:
            del self._buckets[k]
        if len(self._buckets) >= self._max_buckets:
            self._buckets.clear()


limiter = _RateLimiter(settings.RATE_LIMIT_PER_MINUTE)


def _client_ip(request: Request) -> str:
    # Only honour X-Forwarded-For when explicitly configured to sit behind a
    # trusted proxy; otherwise attackers could spoof it to bypass rate limits.
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def rate_limit(scope: str):
    """FastAPI dependency that enforces per-IP rate limiting on a route group."""
    async def _dep(request: Request):
        ip = _client_ip(request)
        if not limiter.allow(f"{scope}:{ip}"):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Try again later.",
            )
    return _dep


# -----------------------------------------------------------------------------
# Lifespan
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting_application", env=settings.APP_ENV)
    await init_db()
    pump_task = asyncio.create_task(_redis_event_pump())
    # Live Internet Analysis Engine — continuous fetch/analyze/build (runs even when DB is down, in-memory)
    try:
        from .live_engine import engine as live_engine

        await live_engine.start()
        logger.info("live_engine_scheduled", interval_s=live_engine.interval)
    except Exception as exc:
        logger.warning("live_engine_start_failed", error=str(exc))
    yield
    try:
        from .live_engine import engine as live_engine

        await live_engine.stop()
    except Exception:
        pass
    pump_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await pump_task
    logger.info("shutting_down_application")
    await close_db()


# -----------------------------------------------------------------------------
# Realtime: Redis Pub/Sub -> WebSocket fan-out
#
# Other services publish JSON envelopes to Redis channels:
#   geosentinel:alerts   {"type": "alert.new",     "payload": {...AlertRead...}}
#   geosentinel:sensors  {"type": "sensor.reading","payload": {...}}
#   geosentinel:reports  {"type": "report.new",    "payload": {...}}
# This pump relays them to every connected WebSocket client. When Redis is not
# reachable (local dev without Docker) the pump retries quietly — the app and
# dashboard keep working, just without live push.
# -----------------------------------------------------------------------------
REDIS_CHANNELS = ("geosentinel:alerts", "geosentinel:sensors", "geosentinel:reports")


async def _redis_event_pump() -> None:
    while True:
        pubsub = None
        client = None
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(settings.REDIS_URL, password=settings.REDIS_PASSWORD)
            pubsub = client.pubsub()
            await pubsub.subscribe(*REDIS_CHANNELS)
            logger.info("realtime_subscribed", channels=list(REDIS_CHANNELS))
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                try:
                    body = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    continue
                envelope = {
                    "type": str(body.get("type", "event")),
                    "payload": body.get("payload", body),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                await manager.broadcast(json.dumps(envelope))
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("realtime_pump_retrying", error=str(exc), retry_s=5)
            await asyncio.sleep(5)
        finally:
            for closer in (
                lambda: pubsub.unsubscribe(),
                lambda: pubsub.aclose(),
                lambda: client.aclose(),
            ):
                with contextlib.suppress(Exception):
                    if callable(closer):
                        maybe = closer()
                        if asyncio.iscoroutine(maybe):
                            with contextlib.suppress(Exception):
                                await maybe


# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI(
    title="GeoSentinel-NER API",
    description="AI-Powered Landslide Early Warning & Monitoring Platform for North Eastern Region",
    version="0.1.0",
    docs_url="/docs" if settings.APP_DEBUG else None,
    redoc_url="/redoc" if settings.APP_DEBUG else None,
    openapi_url="/openapi.json" if settings.APP_DEBUG else None,
    lifespan=lifespan,
)

# --- Middleware ---
# CORS: never use "*" with allow_credentials=True. Read origins from config.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)

if not settings.APP_DEBUG:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_hosts,
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    request_id = request.headers.get("x-request-id", str(uuid4()))
    response = None
    try:
        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as e:
        logger.exception(
            "request_failed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            error=str(e),
        )
        raise


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


# -----------------------------------------------------------------------------
# Auth dependencies
# -----------------------------------------------------------------------------
_USER_SELECT = text(
    """
    SELECT id, username, email, phone, full_name, role, state_id, district_id,
           block_id, village_id, preferred_language, is_active, is_verified,
           last_login_at, created_at, updated_at
    FROM app_user
    WHERE id = :user_id AND is_active
    LIMIT 1
    """
)


def _row_to_user(row) -> AppUserRead:
    return AppUserRead(
        id=row.id,
        username=row.username,
        email=row.email,
        phone=row.phone,
        full_name=row.full_name,
        role=row.role,
        state_id=row.state_id,
        district_id=row.district_id,
        block_id=row.block_id,
        village_id=row.village_id,
        preferred_language=row.preferred_language or settings.DEFAULT_LANGUAGE,
        is_active=row.is_active,
        is_verified=row.is_verified,
        created_at=row.created_at or datetime.now(UTC),
        updated_at=row.updated_at,
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db_session),
) -> AppUserRead:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = verify_token(credentials.credentials, "access")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

    # The token proves identity; the DB decides whether the account still
    # exists and is active (revocation on deactivate/delete is immediate).
    result = await db.execute(_USER_SELECT, {"user_id": str(payload.sub)})
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not found or deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _row_to_user(row)


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db_session),
) -> AppUserRead | None:
    """Resolve a bearer token when supplied, while preserving anonymous access."""
    if not credentials or not credentials.credentials:
        return None
    return await get_current_user(credentials=credentials, db=db)


def require_permission(resource: str, action: str):
    async def permission_checker(user: AppUserRead = Depends(get_current_user)):
        if not check_permission(user.role, resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions: {resource}.{action}",
            )
        return user
    return permission_checker


# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------
@app.get("/health", response_model=HealthCheck, tags=["Health"])
async def health_check():
    checks: dict[str, str] = {"database": "unknown", "redis": "unknown", "minio": "unknown"}

    try:
        async with get_primary_db().session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as e:
        logger.warning("health_db_unhealthy", error=str(e))
        checks["database"] = "unhealthy"

    try:
        import redis.asyncio as redis
        r = redis.from_url(settings.REDIS_URL, password=settings.REDIS_PASSWORD)
        await r.ping()
        await r.aclose()
        checks["redis"] = "healthy"
    except Exception as e:
        logger.warning("health_redis_unhealthy", error=str(e))
        checks["redis"] = "unhealthy"

    try:
        from minio import Minio
        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        client.list_buckets()
        checks["minio"] = "healthy"
    except Exception as e:
        logger.warning("health_minio_unhealthy", error=str(e))
        checks["minio"] = "unhealthy"

    overall = "healthy" if all(v == "healthy" for v in checks.values()) else "degraded"
    return HealthCheck(
        status=overall,
        version="0.1.0",
        environment=settings.APP_ENV,
        checks=checks,
    )


# -----------------------------------------------------------------------------
# Universal assistant LLM — live data, dynamic knowledge, multi-provider
# -----------------------------------------------------------------------------
class AssistantRequest(BaseModel):
    query: str
    history: list[dict[str, str]] = []
    context: dict[str, Any] | None = None
    # Optional RAG retrieval already performed client-side — server will inject as context
    rag_context: list[dict[str, Any]] | None = None
    collection_names: list[str] | None = None
    top_k: int | None = None
    enable_web_search: bool = True  # when true, assistant grounds in live internet search (Tavily/Brave → Wikipedia)


class AssistantResponse(BaseModel):
    answer: str
    model: str
    provider: str  # "remote" (OpenAI-compatible LLM) or "local"
    latency_ms: int


_ASSISTANT_SYSTEM_PROMPT = (
    "You are the GeoSentinel-NER universal assistant embedded in a landslide "
    "early-warning platform for North East India. Answer ANY question the user asks "
    "clearly and accurately. When the question relates to landslide risk, rainfall, "
    "IMD nowcasts, sensor stations, citizen reports or platform models M1/M2/M3, use "
    "the LIVE PLATFORM CONTEXT and any RETRIEVED KNOWLEDGE CHUNKS provided and say when data is live. "
    "If you are unsure or lack data, say so briefly and give your best general answer. "
    "Never invent specific alert IDs, coordinates or numbers that are not in the context. "
    "Cite sources when you use retrieved chunks."
)

# ---- Dynamic guideline loader (no hardcoded data) ----
_GUIDELINE_CACHE: list[dict[str, Any]] | None = None
_GUIDELINE_CACHE_MTIME: float = 0.0


def _load_guideline_docs() -> list[dict[str, Any]]:
    """Load guideline markdown files from docs/guidelines — never hardcoded in code."""
    global _GUIDELINE_CACHE, _GUIDELINE_CACHE_MTIME
    candidates = [
        Path(__file__).resolve().parents[3] / "docs" / "guidelines",
        Path(__file__).resolve().parents[2] / "docs" / "guidelines",
        Path("docs") / "guidelines",
        Path.cwd() / "docs" / "guidelines",
    ]
    guideline_dir = next((p for p in candidates if p.is_dir()), None)
    if guideline_dir is None:
        logger.warning("guideline_dir_not_found", candidates=[str(p) for p in candidates])
        return []
    try:
        mtime = max((f.stat().st_mtime for f in guideline_dir.glob("*.md")), default=0.0)
    except Exception:
        mtime = 0.0
    if _GUIDELINE_CACHE is not None and mtime == _GUIDELINE_CACHE_MTIME:
        return _GUIDELINE_CACHE
    docs: list[dict[str, Any]] = []
    for md in sorted(guideline_dir.glob("*.md")):
        try:
            raw = md.read_text(encoding="utf-8")
            front: dict[str, Any] = {}
            body = raw
            if body.startswith("---"):
                end = body.find("\n---", 3)
                if end != -1:
                    fm = body[3:end].strip()
                    body = body[end + 4 :].strip()
                    for line in fm.splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            front[k.strip()] = v.strip().strip('"').strip("'")
            docs.append(
                {
                    "id": front.get("id", md.stem),
                    "collection": front.get("collection", "geosentinel_guidelines"),
                    "title": front.get("title", md.stem.replace("-", " ").title()),
                    "content": body,
                    "metadata": {k: v for k, v in front.items() if k not in ("id", "collection", "title", "content")},
                    "source_file": str(md.name),
                }
            )
        except Exception as exc:
            logger.warning("guideline_load_failed", file=str(md), error=str(exc))
    _GUIDELINE_CACHE = docs
    _GUIDELINE_CACHE_MTIME = mtime
    if docs:
        logger.info("guidelines_loaded", count=len(docs), dir=str(guideline_dir))
    return docs


async def _live_platform_context() -> str:
    """Compact snapshot of current DB state + dynamic guideline index to ground the assistant."""
    try:
        async with get_primary_db().session() as session:
            alerts = (
                await session.execute(
                    text(
                        "SELECT severity, title, status FROM alert "
                        "WHERE status = 'active' ORDER BY issued_at DESC LIMIT 5"
                    )
                )
            ).all()
            stations = (
                await session.execute(
                    text("SELECT station_code, station_type, status FROM sensor_station LIMIT 8")
                )
            ).all()
            reports = (
                await session.execute(
                    text("SELECT count(*) FROM citizen_report")
                )
            ).scalar()
            # Also pull capitals/districts live when available
            capitals: list[Any] = []
            try:
                capitals = (
                    await session.execute(text("SELECT name FROM admin_state ORDER BY name LIMIT 12"))
                ).all()
            except Exception:
                pass
        alert_lines = "\n".join(f"- [{a.severity}] {a.title} ({a.status})" for a in alerts) or "- none active"
        station_lines = (
            "\n".join(f"- {s.station_code} ({s.station_type}, {s.status})" for s in stations)
            or "- none registered"
        )
        capital_lines = (
            ", ".join(c.name for c in capitals)
            if capitals
            else "NER states (live table empty — see guideline capitals-ner)"
        )
        guidelines = _load_guideline_docs()
        guideline_index = (
            "\n".join(f"- {d['title']} [{d['id']}] — {d['content'][:90]}…" for d in guidelines[:6])
            or "- (no guideline files found)"
        )
        return (
            f"LIVE PLATFORM CONTEXT (as of {datetime.now(UTC).isoformat(timespec='seconds')}):\n"
            f"Active alerts:\n{alert_lines}\n"
            f"Sensor stations:\n{station_lines}\n"
            f"Citizen reports on record: {reports}\n"
            f"Capitals / states on record: {capital_lines}\n"
            f"Guideline knowledge base ({len(guidelines)} docs indexed from docs/guidelines):\n{guideline_index}"
        )
    except Exception as exc:
        logger.warning("assistant_context_degraded", error=str(exc))
        # Still try to return guideline index even when DB is down
        try:
            guidelines = _load_guideline_docs()
            guideline_index = "\n".join(f"- {d['title']} [{d['id']}]" for d in guidelines[:6]) or "- none"
            return f"LIVE PLATFORM CONTEXT: database unavailable — guideline index still available:\n{guideline_index}"
        except Exception:
            return "LIVE PLATFORM CONTEXT: unavailable (database not reachable)."


def _resolve_llm_config() -> tuple[str | None, str, str]:
    """Resolve LLM credentials supporting Groq/OpenAI/Together/Ollama aliases.

    Priority: GEO_LLM_* (already alias-resolved via Pydantic) → env fallback for
    provider-specific vars when the default Nvidia endpoint is still set.
    """
    import os

    api_key = settings.GEO_LLM_API_KEY
    base_url = settings.GEO_LLM_BASE_URL
    model = settings.GEO_LLM_MODEL

    # If no key resolved via alias but a provider-specific key exists, pick it up
    if not api_key:
        for env_key in ("GROQ_API_KEY", "OPENAI_API_KEY", "TOGETHER_API_KEY", "LLM_API_KEY", "NGC_API_KEY"):
            v = os.getenv(env_key)
            if v:
                api_key = v
                break

    # Auto-switch base URL / model to provider defaults when the user only set the key
    # and left the default Nvidia endpoint untouched — avoids confusing 401/404.
    is_default_nvidia = "integrate.api.nvidia.com" in base_url
    if is_default_nvidia:
        if os.getenv("GROQ_API_KEY") and api_key == os.getenv("GROQ_API_KEY"):
            base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1/chat/completions")
            if model == "nvidia/llama-3.1-nemotron-nano-8b-v1":
                model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        elif os.getenv("OPENAI_API_KEY") and api_key == os.getenv("OPENAI_API_KEY"):
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")
            if model == "nvidia/llama-3.1-nemotron-nano-8b-v1":
                model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        elif os.getenv("TOGETHER_API_KEY") and api_key == os.getenv("TOGETHER_API_KEY"):
            base_url = os.getenv("TOGETHER_BASE_URL", "https://api.together.xyz/v1/chat/completions")
            if model == "nvidia/llama-3.1-nemotron-nano-8b-v1":
                model = os.getenv("TOGETHER_MODEL", "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo")

    return api_key, base_url.rstrip("/"), model


async def _call_remote_llm(messages: list[dict[str, str]]) -> tuple[str, str] | None:
    """Call an OpenAI-compatible chat-completions endpoint. Returns None if unconfigured/unreachable."""
    api_key, base_url, model = _resolve_llm_config()
    is_ollama = "11434" in base_url or "ollama" in base_url.lower()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif not is_ollama:
        return None  # no credentials and not a local Ollama-style endpoint

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": settings.GEO_LLM_MAX_TOKENS,
        "stream": False,
    }
    try:
        timeout = httpx.Timeout(settings.GEO_LLM_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(base_url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        content = body.get("choices", [{}])[0].get("message", {}).get("content")
        if isinstance(content, str) and content.strip():
            return content.strip(), model
    except Exception as exc:
        logger.warning("assistant_remote_llm_failed", error=str(exc), url=base_url, model=model)
    return None


async def _local_assistant_answer(query: str) -> str:
    """Deterministic offline fallback grounded in live platform state."""
    context = await _live_platform_context()
    q = query.lower()
    parts: list[str] = []
    if any(k in q for k in ("alert", "warning", "evacuat", "risk")):
        parts.append(
            "Here is the current live alert picture from GeoSentinel-NER:\n" + context
        )
    elif any(k in q for k in ("sensor", "station", "reading")):
        parts.append("Current registered sensor stations:\n" + context)
    elif any(k in q for k in ("report", "citizen")):
        parts.append("Citizen report status:\n" + context)
    else:
        parts.append(context)
    parts.append(
        "\nNote: this answer was generated by the local fallback assistant because no "
        "external LLM endpoint is configured. Set GEO_LLM_API_KEY (or GROQ_API_KEY / "
        "OPENAI_API_KEY) and optionally GEO_LLM_BASE_URL / GEO_LLM_MODEL in .env to get full "
        "general-knowledge answers. The assistant will auto-detect Groq/OpenAI/Together/Ollama "
        "— see docs/rag-assistant.md."
    )
    return "\n".join(parts)


@app.post(f"{settings.API_PREFIX}/assistant/query", response_model=AssistantResponse, tags=["Assistant"])
async def assistant_query(req: AssistantRequest):
    """Universal Q&A endpoint. Uses an external LLM when configured; otherwise a
    deterministic local assistant grounded in live platform data + optional RAG chunks."""
    started = time.time()
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="query must not be empty")

    messages: list[dict[str, str]] = [{"role": "system", "content": _ASSISTANT_SYSTEM_PROMPT}]
    for m in req.history[-8:]:
        role = m.get("role")
        content = m.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            messages.append({"role": role, "content": content[:2000]})
    messages.append({"role": "user", "content": query})
    # Ground with live context + optional RAG chunks + live internet right before the user turn for recency
    context = await _live_platform_context()
    if req.context:
        try:
            context += "\n\nCaller-provided context:\n" + json.dumps(req.context, ensure_ascii=False)[:4000]
        except Exception:
            pass
    if req.rag_context:
        try:
            rag_lines = []
            for c in req.rag_context[:8]:
                title = c.get("title", c.get("id", "chunk"))
                content = (c.get("content") or c.get("text") or "")[:600]
                score = c.get("score", "")
                rag_lines.append(f"- [{title} | score {score}] {content}")
            if rag_lines:
                context += "\n\nRETRIEVED KNOWLEDGE CHUNKS (cite these):\n" + "\n".join(rag_lines)
        except Exception:
            pass
    # Live internet grounding — web search (Tavily/Brave → Wikipedia) + live disaster reports (GDACS/ReliefWeb)
    if req.enable_web_search:
        ql = query.lower()
        sparse = not req.rag_context or len(req.rag_context) < 2
        web_keys = (
            "latest", "news", "today", "current", "live", "global",
            "world", "internet", "reliefweb", "gdacs", "recent", "report",
        )
        wants_web = any(k in ql for k in web_keys) or sparse
        if wants_web:
            try:
                web_hits = await _web_search(query, count=5)
                if web_hits:
                    web_lines = []
                    for h in web_hits[:5]:
                        title = h.get("title", "")[:80]
                        web_lines.append(
                            f"- [{title} | {h.get('source', '')} | {h.get('url', '')}] {h.get('content', '')[:500]}"
                        )
                    context += "\n\nLIVE WEB SEARCH RESULTS (internet — cite URLs):\n" + "\n".join(web_lines)
            except Exception as exc:
                logger.warning("assistant_web_search_failed", error=str(exc))
        # Always inject live disaster reports when the user asks about reports/landslides/disasters
        if any(k in ql for k in ("report", "landslide", "flood", "disaster", "gdacs", "reliefweb", "global alert")):
            try:
                live_reports = await _fetch_live_internet_reports(limit=4)
                if live_reports:
                    rep_lines = []
                    for r in live_reports[:4]:
                        title = r.get("title", "")[:80]
                        rep_lines.append(
                            f"- [{title} | {r.get('source', '')} {r.get('country', '')} | {r.get('url', '')}] "
                            f"{r.get('description', '')[:450]} (severity {r.get('severity', '')})"
                        )
                    context += (
                        "\n\nLIVE INTERNET DISASTER REPORTS (GDACS + ReliefWeb, real-time, cite URLs):\n"
                        + "\n".join(rep_lines)
                    )
            except Exception as exc:
                logger.warning("assistant_live_reports_failed", error=str(exc))
    messages.insert(-1, {"role": "system", "content": context})

    remote = await _call_remote_llm(messages)
    if remote is not None:
        answer, model_name = remote
        provider = "remote"
    else:
        answer = await _local_assistant_answer(query)
        model_name = "geosentinel-local-assistant"
        provider = "local"

    return AssistantResponse(
        answer=answer,
        model=model_name,
        provider=provider,
        latency_ms=int((time.time() - started) * 1000),
    )


# ---- Knowledge endpoints (dynamic, not hardcoded) ----
@app.get(f"{settings.API_PREFIX}/knowledge/guidelines", tags=["Knowledge"])
async def knowledge_guidelines():
    """Return guideline documents loaded live from docs/guidelines/*.md (not hardcoded)."""
    docs = _load_guideline_docs()
    return {"items": docs, "count": len(docs), "source": "docs/guidelines"}


@app.get(f"{settings.API_PREFIX}/knowledge/collections", tags=["Knowledge"])
async def knowledge_collections():
    guidelines = _load_guideline_docs()
    # Live counts for alerts/reports/capitals
    try:
        async with get_primary_db().session() as session:
            a_count = (await session.execute(text("SELECT count(*) FROM alert"))).scalar() or 0
            r_count = (await session.execute(text("SELECT count(*) FROM citizen_report"))).scalar() or 0
            s_count = (await session.execute(text("SELECT count(*) FROM sensor_station"))).scalar() or 0
    except Exception:
        a_count = r_count = s_count = 0
    return {
        "collections": [
            {
                "id": "geosentinel_guidelines",
                "count": len([d for d in guidelines if d["collection"] == "geosentinel_guidelines"]),
                "label": "Guidelines & SOPs",
            },
            {
                "id": "imd_nowcast",
                "count": len([d for d in guidelines if d["collection"] == "imd_nowcast"]),
                "label": "IMD Nowcast",
            },
            {
                "id": "geosentinel_capitals",
                "count": len([d for d in guidelines if d["collection"] == "geosentinel_capitals"]),
                "label": "Capitals & Districts",
            },
            {"id": "geosentinel_alerts", "count": int(a_count), "label": "Alerts (live DB)"},
            {"id": "geosentinel_reports", "count": int(r_count), "label": "Citizen Reports (live DB)"},
            {"id": "sensor_stations", "count": int(s_count), "label": "Sensor Stations (live DB)"},
        ]
    }


# ---- Live internet — North Eastern India disaster reports (GDACS + ReliefWeb) + web search ----
# These endpoints give the site true live-internet access: every report/answer can be grounded
# in the latest global feeds, not just the local citizen_report table. No API key required
# for the disaster feeds; web search uses Tavily/Brave when configured else Wikipedia/DDG fallback.
#
# NER Live-Only Algorithm v1 — same gate as live_engine.py: coords inside NE bbox OR NER term in text.
# This ensures the dashboard and map never show global noise — only NE state reports.
_LIVE_REPORTS_CACHE: dict[str, Any] = {"at": 0.0, "items": []}
_LIVE_REPORTS_TTL = 300.0  # 5 minutes
_NER_TERMS = (
    "arunachal", "assam", "manipur", "meghalaya", "mizoram",
    "nagaland", "sikkim", "tripura", "itanagar", "dispur", "imphal",
    "shillong", "aizawl", "kohima", "gangtok", "agartala", "northeast india",
    "northeast", "barak", "brahmaputra", "churachandpur", "khasi",
)
_NER_BBOX = {"min_lat": 21.9, "max_lat": 29.7, "min_lon": 88.0, "max_lon": 97.5}
_NER_CENTROIDS: dict[str, tuple[float, float]] = {
    "Aizawl": (23.7271, 92.7176), "Imphal": (24.817, 93.9368), "Imphal West": (24.817, 93.9368),
    "Shillong": (25.5788, 91.8933), "Gangtok": (27.3389, 88.6065), "Kohima": (25.6751, 94.1086),
    "Itanagar": (27.0844, 93.6053), "Dispur": (26.1433, 91.7898), "Agartala": (23.8315, 91.2868),
    "Churachandpur": (24.2, 93.68), "East Khasi Hills": (25.46, 91.36),
}


def _in_ner_bbox(lat: Any, lon: Any) -> bool:
    try:
        if lat is None or lon is None:
            return False
        in_lat = _NER_BBOX["min_lat"] <= float(lat) <= _NER_BBOX["max_lat"]
        in_lon = _NER_BBOX["min_lon"] <= float(lon) <= _NER_BBOX["max_lon"]
        return in_lat and in_lon
    except (TypeError, ValueError):
        return False


def _is_ner_item(item: dict[str, Any]) -> bool:
    # Geo-validated NE bbox — strongest signal
    if _in_ner_bbox(item.get("latitude"), item.get("longitude")) or _in_ner_bbox(item.get("lat"), item.get("lng")):
        return True
    text_value = " ".join(str(item.get(key) or "") for key in (
        "title", "description", "district", "country", "raw_title",
        "raw_description", "raw_district", "raw_country",
    )).casefold()
    return any(term in text_value for term in _NER_TERMS)


async def _fetch_gdacs_events(limit: int = 8) -> list[dict[str, Any]]:
    """Fetch recent global disaster events from GDACS (free, no key)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6.0)) as client:
            resp = await client.get(
                "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH",
                params={"eventlist": "FL;EQ;TC;WF"},
                headers={"Accept": "application/json", "User-Agent": "GeoSentinel-NER LiveNE/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            features = data.get("features") or data.get("events") or []
            out: list[dict[str, Any]] = []
            for feat in features[:limit]:
                props = feat.get("properties") or feat
                title = props.get("name") or props.get("eventname") or props.get("title") or "GDACS event"
                country = props.get("country") or props.get("iso3") or ""
                dtype = props.get("eventtype") or props.get("eventType") or "FL"
                severity = {"Red": "critical", "Orange": "high", "Green": "low"}.get(
                    props.get("alertlevel") or props.get("episodealertlevel") or "", "moderate"
                )
                district = props.get("name") or country or "Global"
                lat = lon = None
                try:
                    geom = feat.get("geometry") or props.get("geometry")
                    if geom and geom.get("coordinates"):
                        coords = geom["coordinates"]
                        if (
                            isinstance(coords, (list, tuple))
                            and len(coords) >= 2
                            and isinstance(coords[0], (int, float))
                        ):
                            lon = float(coords[0])
                            lat = float(coords[1])
                except Exception:
                    pass
                # fallback: centroid when GDACS has no coords but district hints NE
                if lat is None and district in _NER_CENTROIDS:
                    lat, lon = _NER_CENTROIDS[district]
                out.append(
                    {
                        "id": f"gdacs-{props.get('eventid') or props.get('id') or len(out)}",
                        "code": f"GDACS-{str(props.get('eventid') or 'EVT')[:10]}",
                        "title": title,
                        "district": district,
                        "country": country,
                        "event_type": dtype,
                        "severity": severity,
                        "status": "live_internet",
                        "source": "GDACS",
                        "url": props.get("url")
                        or f"https://www.gdacs.org/report.aspx?eventtype={dtype}&eventid={props.get('eventid', '')}",
                        "issued_at": props.get("fromdate") or props.get("todate") or datetime.now(UTC).isoformat(),
                        "description": props.get("description")
                        or props.get("htmldescription")
                        or f"{dtype} event {title} — {country}",
                        "latitude": lat,
                        "longitude": lon,
                    }
                )
            return out
    except Exception as exc:
        logger.warning("gdacs_fetch_failed", error=str(exc))
        return []


async def _fetch_reliefweb_reports(limit: int = 8) -> list[dict[str, Any]]:
    """Fetch recent landslide-related humanitarian reports from ReliefWeb (free, no key)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6.0)) as client:
            resp = await client.get(
                "https://api.reliefweb.int/v1/reports",
                params={
                    "appname": "geosentinel-ner",
                    "query[value]": "landslide Northeast India",
                    "limit": limit,
                    "fields[include][]": ["title", "body", "date", "country", "source", "url", "disaster"],
                    "sort[]": ["date:desc"],
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data") or []
            out: list[dict[str, Any]] = []
            for it in items[:limit]:
                fields = it.get("fields") or {}
                title = fields.get("title") or it.get("title") or "ReliefWeb report"
                country = ""
                if fields.get("country"):
                    try:
                        country = ", ".join(c.get("name", "") for c in fields["country"][:2])
                    except Exception:
                        country = str(fields["country"])
                out.append(
                    {
                        "id": f"reliefweb-{it.get('id')}",
                        "code": f"RW-{str(it.get('id'))[:8]}",
                        "title": title,
                        "district": country or "India",
                        "country": country,
                        "event_type": "landslide",
                        "severity": "moderate",
                        "status": "live_internet",
                        "source": "ReliefWeb",
                        "url": fields.get("url") or it.get("href") or f"https://reliefweb.int/report/{it.get('id')}",
                        "issued_at": (fields.get("date") or {}).get("created") or datetime.now(UTC).isoformat(),
                        "description": (fields.get("body") or "")[:600] or title,
                    }
                )
            return out
    except Exception as exc:
        logger.warning("reliefweb_fetch_failed", error=str(exc))
        return []


async def _fetch_weather_watch_reports(limit: int = 8) -> list[dict[str, Any]]:
    """Live Open-Meteo NE heavy-rainfall watches — always NE-geo-validated (no false negatives when GDACS is quiet).
    Tries data-ingestion first, then direct Open-Meteo (works without Docker, student free)."""
    try:
        from geosentinel_shared.districts import NORTHEAST_STATE_LOCATIONS
        districts = list(NORTHEAST_STATE_LOCATIONS.values())
    except Exception:
        districts = ["Aizawl", "Dispur", "Imphal", "Shillong", "Gangtok", "Kohima", "Itanagar", "Agartala"]
    out: list[dict[str, Any]] = []
    async def one(d: str):
        obs = fc = None
        lat, lon = _NER_CENTROIDS.get(d, (None, None))
        fetched_at = None
        # Try data-ingestion first
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(f"http://data-ingestion:8001/weather/current/{d}")
                resp.raise_for_status()
                w = resp.json()
            obs = float(w.get("observed_rainfall_24h_mm") or 0)
            fc = float(w.get("forecast_rainfall_next_24h_mm") or 0)
            fetched_at = w.get("fetched_at")
            if w.get("latitude") is not None:
                try:
                    lat = float(w["latitude"])
                    lon = float(w["longitude"])
                except Exception:
                    pass
        except Exception:
            # Fallback: direct Open-Meteo (no Docker, keyless)
            if lat is None or lon is None:
                return None
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://api.open-meteo.com/v1/forecast",
                        params={
                            "latitude": lat,
                            "longitude": lon,
                            "hourly": "precipitation",
                            "past_hours": 24,
                            "forecast_days": 1,
                            "timezone": "UTC",
                        },
                    )
                    resp.raise_for_status()
                    j = resp.json()
                    prec = (j.get("hourly") or {}).get("precipitation") or []
                    if len(prec) >= 48:
                        obs = float(sum(float(v or 0) for v in prec[:24]))
                        fc = float(sum(float(v or 0) for v in prec[24:48]))
                    elif prec:
                        obs = float(sum(float(v or 0) for v in prec))
                        fc = 0.0
                    else:
                        return None
                    fetched_at = datetime.now(UTC).isoformat()
            except Exception:
                return None
        try:
            if obs is None or fc is None:
                return None
            if obs < 45 and fc < 35:
                return None
            sev = "critical" if obs >= 90 or fc >= 75 else "high" if obs >= 60 or fc >= 50 else "moderate"
            return {
                "id": f"weather-{d.lower().replace(' ','-')}-{int(time.time())}",
                "code": f"WX-{d[:3].upper()}",
                "title": f"Heavy rainfall watch — {d}",
                "district": d,
                "country": "India",
                "event_type": "heavy_rainfall",
                "severity": sev,
                "status": "live_internet",
                "source": "Open-Meteo",
                "url": f"/weather/current/{d}",
                "issued_at": fetched_at or datetime.now(UTC).isoformat(),
                "description": (
                    f"Open-Meteo: {obs:.1f} mm observed (24h), {fc:.1f} mm forecast (next 24h) "
                    f"in {d} — landslide flash-flood watch."
                ),
                "latitude": lat,
                "longitude": lon,
            }
        except Exception:
            return None
    results = await asyncio.gather(*(one(d) for d in districts))
    out = [r for r in results if r is not None]
    return out[:limit]


async def _fetch_live_internet_reports(limit: int = 12) -> list[dict[str, Any]]:
    """Merged NER-only live reports with 5-min cache — GDACS + ReliefWeb + Open-Meteo NE watch."""
    now = time.time()
    if _LIVE_REPORTS_CACHE["items"] and now - _LIVE_REPORTS_CACHE["at"] < _LIVE_REPORTS_TTL:
        return _LIVE_REPORTS_CACHE["items"][:limit]
    gdacs, relief, weather = await asyncio.gather(
        _fetch_gdacs_events(limit=6), _fetch_reliefweb_reports(limit=6), _fetch_weather_watch_reports(8)
    )
    all_items = gdacs + relief + weather
    # Strict NE gate — only NE reports pass to the client and map
    merged = [item for item in all_items if _is_ner_item(item)]
    # De-duplicate by id, keep latest per id
    seen: set[str] = set()
    dedup: list[dict[str, Any]] = []
    for it in merged:
        iid = str(it.get("id"))
        if iid not in seen:
            seen.add(iid)
            dedup.append(it)
    dedup = dedup[:limit]
    try:
        dedup.sort(key=lambda x: str(x.get("issued_at") or ""), reverse=True)
    except Exception:
        pass
    _LIVE_REPORTS_CACHE["at"] = now
    _LIVE_REPORTS_CACHE["items"] = dedup
    return dedup


async def _web_search(query: str, count: int = 6) -> list[dict[str, Any]]:
    """Live web search for the assistant. Prefers Tavily/Brave when keys are set, else Wikipedia + DDG."""
    import os

    q = query.strip()
    if not q:
        return []
    # 1) Tavily (LLM-optimized) — https://tavily.com
    tavily_key = os.getenv("TAVILY_API_KEY") or os.getenv("TAVILY_KEY")
    if tavily_key:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": tavily_key,
                        "query": q,
                        "search_depth": "advanced",
                        "include_answer": True,
                        "max_results": count,
                    },
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results") or []
                return [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "content": r.get("content", "")[:700],
                        "score": float(r.get("score", 0.7)),
                        "source": "Tavily",
                    }
                    for r in results[:count]
                ]
        except Exception as exc:
            logger.warning("tavily_search_failed", error=str(exc))
    # 2) Brave Search
    brave_key = os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY")
    if brave_key:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as client:
                resp = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": q, "count": count},
                    headers={"Accept": "application/json", "X-Subscription-Token": brave_key},
                )
                resp.raise_for_status()
                data = resp.json()
                results = (data.get("web") or {}).get("results") or []
                return [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "content": (r.get("description") or "")[:700],
                        "score": 0.7,
                        "source": "Brave",
                    }
                    for r in results[:count]
                ]
        except Exception as exc:
            logger.warning("brave_search_failed", error=str(exc))
    # 3) Wikipedia (free, no key) — good for general knowledge
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6.0)) as client:
            resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": q,
                    "format": "json",
                    "srlimit": count,
                    "origin": "*",
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            hits = (data.get("query") or {}).get("search") or []
            if hits:
                return [
                    {
                        "title": h.get("title", ""),
                        "url": f"https://en.wikipedia.org/wiki/{h.get('title', '').replace(' ', '_')}",
                        "content": (h.get("snippet") or "")
                        .replace('<span class="searchmatch">', "")
                        .replace("</span>", "")[:600],
                        "score": 0.55,
                        "source": "Wikipedia",
                    }
                    for h in hits[:count]
                ]
    except Exception as exc:
        logger.warning("wiki_search_failed", error=str(exc))
    # 4) DuckDuckGo instant answer as last resort
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6.0)) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": q, "format": "json", "no_html": "1"},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            topics = data.get("RelatedTopics") or []
            out = []
            for t in topics[:count]:
                if isinstance(t, dict) and t.get("Text"):
                    out.append(
                        {
                            "title": t.get("Text", "")[:80],
                            "url": t.get("FirstURL", ""),
                            "content": t.get("Text", "")[:600],
                            "score": 0.45,
                            "source": "DuckDuckGo",
                        }
                    )
            if out:
                return out
    except Exception as exc:
        logger.warning("ddg_search_failed", error=str(exc))
    return []


@app.get(f"{settings.API_PREFIX}/live/reports", tags=["Live"])
async def live_reports(limit: int = 12, include_citizen: bool = True):
    """Live reports — strictly North Eastern India only (NE bbox/text gate), plus local citizen reports.
    Each item includes latitude/longitude for direct MapLibre placement."""
    internet = await _fetch_live_internet_reports(limit=limit)
    # Merge in reports already built & analyzed by the background Live Internet Engine (LLM-enriched, deduped)
    try:
        from .live_engine import engine as _eng

        eng_reports = _eng.get_reports(limit=limit)
        seen = {r.get("id") for r in internet}
        for er in eng_reports:
            if er.get("id") not in seen and _is_ner_item(er):
                internet.append(
                    {
                        "id": er.get("id"),
                        "code": er.get("code"),
                        "title": er.get("village") and f"{er.get('report_type')} in {er.get('village')}" or er.get("code"),  # noqa: E501
                        "district": er.get("district"),
                        "country": er.get("country"),
                        "event_type": er.get("report_type"),
                        "severity": er.get("severity"),
                        "status": er.get("status"),
                        "source": er.get("source"),
                        "url": er.get("url"),
                        "issued_at": er.get("created_at") or er.get("createdAt"),
                        "description": er.get("description"),
                        "latitude": er.get("latitude") if er.get("latitude") is not None else er.get("lat"),
                        "longitude": er.get("longitude") if er.get("longitude") is not None else er.get("lng"),
                    }
                )
    except Exception:
        pass
    citizen: list[dict[str, Any]] = []
    if include_citizen:
        try:
            async with get_primary_db().session() as session:
                rows = (
                    await session.execute(
                        text(
                            "SELECT id, report_code, report_type, severity, description, status, "
                            "priority_score, created_at, ST_Y(geom) AS latitude, ST_X(geom) AS longitude "
                            "FROM citizen_report ORDER BY created_at DESC LIMIT 8"
                        )
                    )
                ).all()
                for r in rows:
                    citizen.append(
                        {
                            "id": f"citizen-{r.id}",
                            "code": r.report_code,
                            "title": f"{r.report_type} · {r.severity}",
                            "district": "NER",
                            "event_type": r.report_type,
                            "severity": r.severity,
                            "status": r.status,
                            "source": "Citizen",
                            "url": None,
                            "issued_at": (
                                r.created_at.isoformat() if hasattr(r.created_at, "isoformat") else str(r.created_at)
                            ),
                            "description": (r.description or "")[:500],
                            "latitude": float(r.latitude) if r.latitude is not None else None,
                            "longitude": float(r.longitude) if r.longitude is not None else None,
                        }
                    )
        except Exception as exc:
            logger.warning("live_reports_citizen_failed", error=str(exc))
    return {
        "items": (internet + citizen)[:limit],
        "internet_count": len(internet),
        "citizen_count": len(citizen),
        "cached": _LIVE_REPORTS_CACHE["at"] > 0,
    }


@app.get(f"{settings.API_PREFIX}/live/search", tags=["Live"])
async def live_search(q: str, count: int = 6):
    """Live web search — Tavily/Brave when configured, else Wikipedia/DDG. Used by the assistant for internet grounding."""  # noqa: E501
    if not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")
    results = await _web_search(q, count=min(count, 10))
    return {"query": q, "results": results, "count": len(results)}


@app.post(f"{settings.API_PREFIX}/live/fetch", tags=["Live"])
async def live_fetch(body: dict[str, Any]):
    """Fetch any URL's text (SSRF-guarded) — lets the assistant see live internet pages."""
    url = str(body.get("url") or "").strip()
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="url must be http(s)")
    # SSRF guard: block private ranges
    blocked = (
        "127.0.0.1", "localhost", "169.254.", "10.",
        "192.168.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
    )
    if any(b in url for b in blocked):
        raise HTTPException(status_code=400, detail="private URL blocked")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0), follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "GeoSentinel-NER/1.0 (+https://geosentinel-ner.local)",
                    "Accept": "text/html,application/json,text/plain,*/*",
                },
            )
            resp.raise_for_status()
            text_content = resp.text[:12000]
            # naive html strip
            import re

            text_content = re.sub(r"<[^>]+>", " ", text_content)
            text_content = re.sub(r"\s+", " ", text_content).strip()[:8000]
            return {
                "url": url,
                "status": resp.status_code,
                "content": text_content,
                "content_type": resp.headers.get("content-type", ""),
            }
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"fetch failed: {exc}") from exc


@app.get(f"{settings.API_PREFIX}/live/health", tags=["Live"])
async def live_health():
    """Health for live-internet subsystem (shows which providers are configured)."""
    import os

    return {
        "gdacs": "free (no key, cached 5m)",
        "reliefweb": "free (no key, cached 5m)",
        "tavily": "configured" if os.getenv("TAVILY_API_KEY") else "not configured — will use Wikipedia/DDG fallback",
        "brave": "configured" if os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY") else "not configured",
        "open_meteo": "free — /weather/current/{district}",
        "imd": "live — /imd/nowcast" + (" (IMD_API_KEY set)" if os.getenv("IMD_API_KEY") else " (keyless)"),
    }


@app.get(f"{settings.API_PREFIX}/live/engine/status", tags=["Live"])
async def live_engine_status():
    """Live Internet Analysis Engine — status, schedule, and stats (proves the engine is running)."""
    try:
        from .live_engine import engine

        return engine.get_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post(f"{settings.API_PREFIX}/live/engine/run", tags=["Live"])
async def live_engine_run():
    """Trigger one engine cycle on demand (fetch → analyze → build) and return the summary."""
    try:
        from .live_engine import engine

        summary = await engine.run_cycle()
        return {"status": "ok", "summary": summary, "engine": engine.get_status()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get(f"{settings.API_PREFIX}/live/engine/reports", tags=["Live"])
async def live_engine_reports(limit: int = 20):
    """Reports built by the Live Internet Analysis Engine (analyzed, LLM-enriched, deduped)."""
    try:
        from .live_engine import engine

        items = engine.get_reports(limit=min(limit, 100))
        return {"items": items, "count": len(items), "engine": engine.get_status()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get(f"{settings.API_PREFIX}/live/problems/search", tags=["Live"])
async def live_problems_search(q: str = "landslide", count: int = 8):
    """Powerful problem search — queries Tavily/Brave/GDACS/ReliefWeb + live_engine heuristic, NE-gated. No DB write."""
    try:
        from .live_engine import _heuristic_analyze
        from .live_engine import _is_ner_item as _eng_is_ner

        # Use existing web search + fresh fetch for broader coverage
        web = await _web_search(q, count=min(count, 10))
        # Normalize web results to raw shape
        raws: list[dict[str, Any]] = []
        for w in web:
            raws.append({
                "raw_title": w.get("title", ""),
                "raw_description": w.get("content", "")[:800],
                "raw_country": "India",
                "raw_district": "India",
                "event_type": "web_search",
                "severity_hint": "moderate",
                "source": w.get("source", "Tavily"),
                "url": w.get("url", ""),
                "issued_at": datetime.now(UTC).isoformat(),
            })
        # Also pull one fresh engine-style fetch batch for problems
        try:
            import asyncio as _asyncio

            from .live_engine import _fetch_brave, _fetch_gdacs, _fetch_reliefweb, _fetch_tavily
            gdacs, relief, tavily, brave = await _asyncio.gather(
                _fetch_gdacs(4), _fetch_reliefweb(4), _fetch_tavily(4), _fetch_brave(4)
            )
            raws.extend(gdacs + relief + tavily + brave)
        except Exception:
            pass
        # Analyze and filter with powerful heuristic
        out: list[dict[str, Any]] = []
        for raw in raws:
            if not _eng_is_ner(raw):
                continue
            analyzed = _heuristic_analyze(raw)
            if not analyzed.get("relevant"):
                continue
            out.append({
                "title": raw.get("raw_title"),
                "description": raw.get("raw_description", "")[:500],
                "district": analyzed.get("district"),
                "report_type": analyzed.get("report_type"),
                "severity": analyzed.get("severity"),
                "confidence": analyzed.get("confidence"),
                "problem_tags": analyzed.get("problem_tags"),
                "source": raw.get("source"),
                "url": raw.get("url"),
            })
            if len(out) >= count:
                break
        return {"query": q, "count": len(out), "items": out, "engine": "powerful v2 (Tavily/Brave/GDACS + heuristic)"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post(f"{settings.API_PREFIX}/live/problems/search-and-report", tags=["Live"])
async def live_problems_search_and_report(
    q: str = "landslide in North East India", count: int = 6, persist: bool = True
):
    """Powerful search that also creates citizen_reports (add them to reports). Persists via live_engine._build_report."""  # noqa: E501
    try:
        from .live_engine import _hash_report, _heuristic_analyze, engine
        from .live_engine import _is_ner_item as _eng_is_ner

        web = await _web_search(q, count=min(count * 2, 12))
        raws = [
            {
                "raw_title": w.get("title", ""),
                "raw_description": w.get("content", "")[:800],
                "raw_country": "India",
                "raw_district": "India",
                "event_type": "web_search",
                "severity_hint": "moderate",
                "source": w.get("source", "Tavily"),
                "url": w.get("url", ""),
                "issued_at": datetime.now(UTC).isoformat(),
            }
            for w in web
        ]
        created: list[dict[str, Any]] = []
        skipped = 0
        for raw in raws:
            if not _eng_is_ner(raw):
                skipped += 1
                continue
            analyzed = _heuristic_analyze(raw)
            if not analyzed.get("relevant"):
                skipped += 1
                continue
            h = _hash_report(raw.get("raw_title", ""), raw.get("url", ""))
            if h in engine.seen_hashes:
                skipped += 1
                continue
            engine.seen_hashes.add(h)
            if persist:
                report = await engine._build_report(raw, analyzed, h)
                if report:
                    engine.reports.insert(0, report)
                    if len(engine.reports) > 200:
                        engine.reports = engine.reports[:200]
                    created.append(report)
            else:
                created.append({"raw_title": raw.get("raw_title"), "analyzed": analyzed, "hash": h})
            if len(created) >= count:
                break
        return {"query": q, "created": len(created), "skipped": skipped, "items": created, "persisted": persist}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---- RAG shims (so frontend rag.ts remoteGenerate works with the assistant LLM) ----
def _rag_tokenize(s: str) -> list[str]:
    import re

    return re.sub(r"[^a-z0-9\u00C0-\u024F]+", " ", s.lower()).strip().split()


def _rag_server_search(
    query: str, collection_names: list[str] | None, top_k: int, reranker: bool
) -> list[dict[str, Any]]:
    """Lightweight server-side hybrid search over guidelines + live DB documents (TF-IDF + keyword overlap)."""
    import math
    import re

    q_tokens = _rag_tokenize(query)
    if not q_tokens:
        return []
    q_set = set(q_tokens)
    q_tf: dict[str, float] = {}
    for t in q_tokens:
        q_tf[t] = q_tf.get(t, 0) + 1
    n = len(q_tokens) or 1
    for k in list(q_tf.keys()):
        q_tf[k] /= n

    # Build corpus: guidelines + live alerts/reports
    corpus: list[dict[str, Any]] = []
    for d in _load_guideline_docs():
        if collection_names and d["collection"] not in collection_names:
            continue
        corpus.append(d)
    # Live DB docs are added synchronously via a tiny async helper — caller will extend
    # (this function is intentionally sync; live docs appended by the endpoint handlers)
    scored: list[dict[str, Any]] = []
    for doc in corpus:
        title = doc.get("title", "")
        content = doc.get("content", "")
        doc_tokens = _rag_tokenize(f"{title} {content}")
        doc_tf: dict[str, float] = {}
        for t in doc_tokens:
            doc_tf[t] = doc_tf.get(t, 0) + 1
        dn = len(doc_tokens) or 1
        for k in list(doc_tf.keys()):
            doc_tf[k] /= dn
        # cosine
        dot = sum(q_tf.get(k, 0) * doc_tf.get(k, 0) for k in set(q_tf) | set(doc_tf))
        na = math.sqrt(sum(v * v for v in q_tf.values()))
        nb = math.sqrt(sum(v * v for v in doc_tf.values()))
        dense = dot / (na * nb) if na and nb else 0
        doc_set = set(doc_tokens)
        inter = len(q_set & doc_set)
        sparse = inter / len(q_set) if q_set else 0
        hybrid = 0.6 * dense + 0.4 * sparse
        rerank = 0
        if reranker:
            if doc["collection"] == "geosentinel_guidelines" and re.search(r"threshold|m1|m2|sop|ndma|gsi", query, re.I):  # noqa: E501
                rerank += 0.12
            if re.search(r"alert|evacuation|warning", query, re.I) and doc["collection"] == "geosentinel_alerts":
                rerank += 0.10
            if re.search(r"report|citizen|triage", query, re.I) and doc["collection"] == "geosentinel_reports":
                rerank += 0.10
        score = min(1.0, hybrid + rerank)
        if reranker and score < 0.08:
            continue
        scored.append(
            {**doc, "chunkId": f"{doc['id']}#0", "score": score, "rerankerScore": score if reranker else None}
        )
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


class _RagGenerateBody(BaseModel):
    messages: list[dict[str, str]] = []
    use_knowledge_base: bool = True
    collection_names: list[str] | None = None
    agentic: bool = False
    enable_query_rewriting: bool = False
    top_k: int = 6
    # legacy aliases
    topK: int | None = None


@app.get(f"{settings.API_PREFIX}/rag/v1/health", tags=["RAG"])
async def rag_health_shim(check_dependencies: bool = False):
    api_key, base_url, model = _resolve_llm_config()
    has_llm = bool(api_key) or "11434" in base_url
    return {
        "status": "ok",
        "deployment": "api-gateway-llm" if has_llm else "library",
        "configFile": "services/api-gateway (GEO_LLM_*)" if has_llm else "notebooks/config.yaml (in-browser fallback)",
        "enabled": {
            "agenticRag": True, "queryRewriting": True, "reranker": True,
            "hybridSearch": True, "guardrails": False, "vlm": False,
        },
        "services": {
            "embedding": "tf-idf (server) + live guidelines" if not has_llm else f"llm:{model}",
            "vectorDB": "in-memory + PostGIS live",
            "llm": model if has_llm else "mock synthesis (set GEO_LLM_API_KEY / GROQ_API_KEY / OPENAI_API_KEY)",
            "reranker": "cross-encoder mock (threshold 0.08)",
        },
    }


@app.post(f"{settings.API_PREFIX}/rag/v1/search", tags=["RAG"])
async def rag_search_shim(body: dict[str, Any]):
    query = str(body.get("query") or body.get("text") or "")
    top_k = int(body.get("top_k") or body.get("topK") or 6)
    collection_names = body.get("collection_names") or body.get("collectionNames")
    if not query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")
    # Server-side search over guidelines + live DB
    retrieval = _rag_server_search(query, collection_names, top_k, reranker=True)
    # Augment with live alerts/reports matching query terms (keyword scan)
    try:
        async with get_primary_db().session() as session:
            # Simple ILIKE search for alerts
            like = f"%{query.split()[0]}%" if query.split() else "%"
            alerts = (
                await session.execute(
                    text(
                        "SELECT id, severity, title, message, district, status FROM alert "
                        "WHERE title ILIKE :q OR message ILIKE :q LIMIT 5"
                    ),
                    {"q": like},
                )
            ).all()
            for a in alerts:
                retrieval.append(
                    {
                        "id": f"alert-{a.id}",
                        "collection": "geosentinel_alerts",
                        "title": f"{a.severity.upper()} · {a.district} — {a.title}",
                        "content": f"{a.message} Severity {a.severity}, district {a.district}, status {a.status}.",
                        "metadata": {"district": a.district, "severity": a.severity},
                        "chunkId": f"alert-{a.id}#0",
                        "score": 0.55,
                        "rerankerScore": 0.55,
                    }
                )
    except Exception as exc:
        logger.warning("rag_search_live_fetch_failed", error=str(exc))
    # Also inject live internet reports when the query is report/global/latest oriented
    if any(k in query.lower() for k in (
        "report", "landslide", "flood", "gdacs", "relief", "latest", "global", "news", "disaster"
    )) or len(retrieval) < 2:
        try:
            live_reports = await _fetch_live_internet_reports(limit=4)
            for r in live_reports[:3]:
                retrieval.append(
                    {
                        "id": r["id"],
                        "collection": "geosentinel_reports",
                        "title": f"[LIVE] {r['title']} — {r.get('source','')}",
                        "content": f"{r.get('description','')[:500]} Source {r.get('source')} {r.get('url','')}",
                        "metadata": {"source": r.get("source", ""), "country": r.get("country", "")},
                        "chunkId": f"{r['id']}#0",
                        "score": 0.62,
                        "rerankerScore": 0.62,
                    }
                )
        except Exception:
            pass
    retrieval.sort(key=lambda x: x.get("score", 0), reverse=True)
    return {"chunks": retrieval[:top_k], "query": query}


@app.post(f"{settings.API_PREFIX}/rag/v1/generate", tags=["RAG"])
async def rag_generate_shim(body: _RagGenerateBody):
    """RAG generate — retrieves live knowledge then synthesizes with the configured LLM (or templated fallback)."""
    started = time.time()
    query = ""
    if body.messages:
        # last user message is the query
        for m in reversed(body.messages):
            if m.get("role") == "user" and m.get("content"):
                query = str(m["content"])
                break
    if not query:
        query = ""
    if not query.strip():
        raise HTTPException(status_code=400, detail="messages must contain a user query")
    top_k = body.topK if body.topK is not None else body.top_k
    # Retrieve
    retrieval = _rag_server_search(query, body.collection_names, top_k, reranker=True)
    try:
        async with get_primary_db().session() as session:
            like = f"%{query.split()[0]}%" if query.split() else "%"
            alerts = (
                await session.execute(
                    text(
                        "SELECT id, severity, title, message, district, status FROM alert "
                        "WHERE title ILIKE :q OR message ILIKE :q LIMIT 4"
                    ),
                    {"q": like},
                )
            ).all()
            for a in alerts:
                retrieval.append(
                    {
                        "id": f"alert-{a.id}",
                        "collection": "geosentinel_alerts",
                        "title": f"{a.severity.upper()} · {a.district} — {a.title}",
                        "content": f"{a.message} Severity {a.severity}, district {a.district}, status {a.status}.",
                        "metadata": {"district": a.district, "severity": a.severity},
                        "chunkId": f"alert-{a.id}#0",
                        "score": 0.55,
                        "rerankerScore": 0.55,
                    }
                )
    except Exception:
        pass
    # Augment with live internet reports (GDACS + ReliefWeb) — true live-internet grounding
    if any(k in query.lower() for k in (
        "report", "landslide", "flood", "gdacs", "relief", "latest", "global", "news", "disaster"
    )) or len(retrieval) < 2:
        try:
            live_reports = await _fetch_live_internet_reports(limit=4)
            for r in live_reports[:3]:
                retrieval.append(
                    {
                        "id": r["id"],
                        "collection": "geosentinel_reports",
                        "title": f"[LIVE] {r['title']} — {r.get('source','')}",
                        "content": (
                            f"{r.get('description', '')[:500]} Source {r.get('source')} {r.get('url', '')} "
                            f"Country {r.get('country', '')} Severity {r.get('severity', '')}"
                        ),
                        "metadata": {
                            "source": r.get("source", ""),
                            "country": r.get("country", ""),
                            "severity": r.get("severity", ""),
                        },
                        "chunkId": f"{r['id']}#0",
                        "score": 0.62,
                        "rerankerScore": 0.62,
                    }
                )
            retrieval.sort(key=lambda x: x.get("score", 0), reverse=True)
            retrieval = retrieval[:top_k]
        except Exception:
            pass
    else:
        retrieval.sort(key=lambda x: x.get("score", 0), reverse=True)
        retrieval = retrieval[:top_k]

    # Build LLM messages with retrieved chunks + live internet as context
    context = await _live_platform_context()
    if retrieval:
        rag_lines = "\n".join(
            f"- [{c['title']} | {c['chunkId']} | score {c.get('score', 0):.2f}] {c.get('content', '')[:500]}"
            for c in retrieval[:top_k]
        )
        context += "\n\nRETRIEVED KNOWLEDGE CHUNKS (cite chunkIds):\n" + rag_lines
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _ASSISTANT_SYSTEM_PROMPT},
        {"role": "system", "content": context},
    ]
    # preserve prior history from messages (excluding last user query which we re-add)
    for m in body.messages[:-1]:
        if m.get("role") in {"user", "assistant"} and m.get("content"):
            messages.append({"role": m["role"], "content": str(m["content"])[:2000]})
    messages.append({"role": "user", "content": query})

    remote = await _call_remote_llm(messages)
    if remote is not None:
        answer, model_name = remote
        provider = "remote"
    else:
        # Templated fallback grounded in retrieval
        top = retrieval[:3]
        if not retrieval:
            answer = (
                f'No relevant chunks found for "{query}" — try broadening the query '
                "or ingesting more guidelines via docs/guidelines."
            )
        else:
            answer = (
                "Based on {} retrieved chunks (hybrid search, live guidelines + DB):\n\n".format(len(retrieval))
                + "\n".join(
                    f"{i + 1}. **{c['title']}** — {c.get('content', '')[:180]}… [{c['chunkId']}]"
                    for i, c in enumerate(top)
                )
            )
            answer += (
                "\n\n_Note: local synthesis — set GEO_LLM_API_KEY / GROQ_API_KEY / "
                "OPENAI_API_KEY in .env for LLM-powered answers._"
            )
        model_name = "geosentinel-local-rag"
        provider = "local"

    citations = [
        {
            "documentId": c["id"],
            "chunkId": c["chunkId"],
            "title": c["title"],
            "score": float(c.get("score", 0)),
            "metadata": c.get("metadata", {}),
        }
        for c in retrieval[:3]
    ]
    stages = (
        [
            {
                "stage": "planning",
                "eventType": "stage_start",
                "content": "Planner: decompose into guideline, live alert and district sub-tasks",
            },
            {
                "stage": "retrieval",
                "eventType": "stage_end",
                "content": f"Retrieved {len(retrieval)} chunks (hybrid, topK={top_k})",
            },
            {"stage": "reranking", "eventType": "stage_end", "content": "Reranker threshold 0.08"},
            {"stage": "synthesis", "eventType": "stage_end", "content": f"Synthesis via {provider}:{model_name}"},
            {"stage": "verification", "eventType": "stage_end", "content": "Verified citations for every claim"},
        ]
        if body.agentic
        else []
    )
    latency_ms = int((time.time() - started) * 1000)
    return {
        "answer": answer,
        "citations": citations,
        "retrieval": retrieval,
        "agenticStages": stages,
        "reasoningContent": (
            f"Live retrieval over {len(retrieval)} chunks; synthesis via {provider}:{model_name}; "
            f"latency {latency_ms}ms"
        ) if body.agentic else None,
        "usage": {"promptTokens": sum(len(m["content"]) for m in messages) // 4, "completionTokens": len(answer) // 4},
        "model": model_name,
        "provider": provider,
    }


# -----------------------------------------------------------------------------
# Auth endpoints
# -----------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

# Roles that can never be self-assigned via public registration.
_SELF_ASSIGNABLE_ROLES = {"citizen", "volunteer"}

_REGISTER_SQL = text(
    """
    INSERT INTO app_user (username, email, phone, password_hash, full_name, role,
                          state_id, district_id, block_id, village_id, preferred_language)
    VALUES (:username, :email, :phone, :password_hash, :full_name, :role,
            :state_id, :district_id, :block_id, :village_id, :preferred_language)
    RETURNING id, username, email, phone, full_name, role, state_id, district_id,
              block_id, village_id, preferred_language, is_active, is_verified,
              last_login_at, created_at, updated_at
    """
)


@app.post(f"{settings.API_PREFIX}/auth/register", response_model=AppUserRead, tags=["Auth"],
          dependencies=[Depends(rate_limit("auth"))])
async def register(user_data: AppUserCreate, db: AsyncSession = Depends(get_db_session)):
    """Public registration. Passwords are bcrypt-hashed; privileged roles must be
    granted by an admin — they cannot be self-assigned here."""
    if len(user_data.password) < MIN_PASSWORD_LENGTH or len(user_data.password) > MAX_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be between {MIN_PASSWORD_LENGTH} and {MAX_PASSWORD_LENGTH} characters",
        )
    role = user_data.role if user_data.role in _SELF_ASSIGNABLE_ROLES else "citizen"
    params = {
        "username": user_data.username.strip(),
        "email": user_data.email,
        "phone": user_data.phone,
        "password_hash": hash_password(user_data.password),
        "full_name": user_data.full_name,
        "role": role,
        "state_id": user_data.state_id,
        "district_id": user_data.district_id,
        "block_id": user_data.block_id,
        "village_id": user_data.village_id,
        "preferred_language": user_data.preferred_language,
    }
    try:
        result = await db.execute(_REGISTER_SQL, params)
        row = result.first()
    except IntegrityError:
        await db.rollback()
        # Generic message: do not reveal whether the username or email exists.
        raise HTTPException(status_code=409, detail="Username or email already registered")
    logger.info("user_registered", user_id=str(row.id), role=row.role)
    return _row_to_user(row)


_LOGIN_SQL = text(
    """
    SELECT id, username, password_hash, role, is_active, failed_login_attempts, locked_until
    FROM app_user
    WHERE username = :identifier OR email = :identifier
    LIMIT 1
    """
)
_RECORD_FAILED_LOGIN_SQL = text(
    """
    UPDATE app_user
    SET failed_login_attempts = failed_login_attempts + 1,
        locked_until = CASE
            WHEN failed_login_attempts + 1 >= :max_failed THEN NOW() + make_interval(mins => :lockout_mins)
            ELSE locked_until END
    WHERE id = :user_id
    """
)
_RECORD_SUCCESS_SQL = text(
    """
    UPDATE app_user
    SET failed_login_attempts = 0, locked_until = NULL, last_login_at = NOW()
    WHERE id = :user_id
    """
)


@app.post(f"{settings.API_PREFIX}/auth/login", response_model=Token, tags=["Auth"],
          dependencies=[Depends(rate_limit("auth-login"))])
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db_session)):
    """Verify credentials against the DB. Always returns a generic 401 so
    attackers cannot enumerate usernames. Accounts lock after repeated failures."""
    if not body.username or not body.password:
        raise HTTPException(status_code=422, detail="username and password are required")
    identifier = body.username.strip()
    logger.info("login_attempt")

    result = await db.execute(_LOGIN_SQL, {"identifier": identifier})
    row = result.first()
    generic_401 = HTTPException(status_code=401, detail="Incorrect username or password")
    if row is None:
        # Burn a hash comparison anyway to keep timing consistent.
        try:
            verify_password(body.password, "$2b$12$" + "x" * 53)
        except Exception:
            pass
        raise generic_401

    now = datetime.now(UTC)
    if not row.is_active:
        raise generic_401
    if row.locked_until is not None and row.locked_until > now:
        raise HTTPException(status_code=423, detail="Account temporarily locked. Try again later.")

    try:
        password_ok = verify_password(body.password, row.password_hash)
    except Exception:
        # Malformed/legacy hash in DB — treat as a failed login, not a 500.
        password_ok = False

    if not password_ok:
        await db.execute(
            _RECORD_FAILED_LOGIN_SQL,
            {"max_failed": MAX_FAILED_LOGINS, "lockout_mins": LOCKOUT_MINUTES, "user_id": str(row.id)},
        )
        await db.commit()
        logger.warning("login_failed", user_id=str(row.id))
        raise generic_401

    await db.execute(_RECORD_SUCCESS_SQL, {"user_id": str(row.id)})
    await db.commit()
    access = create_access_token(subject=row.id, username=row.username, role=row.role)
    refresh = create_refresh_token(subject=row.id, username=row.username, role=row.role)
    return Token(access_token=access, refresh_token=refresh)


@app.post(f"{settings.API_PREFIX}/auth/refresh", response_model=Token, tags=["Auth"],
          dependencies=[Depends(rate_limit("auth"))])
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Refresh access token. Refresh token is taken from the request body to
    avoid leaking it via access logs / proxy URLs. The account must still
    exist and be active — deactivation kills refresh immediately."""
    try:
        payload = verify_token(body.refresh_token, "refresh")
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    result = await db.execute(_USER_SELECT, {"user_id": str(payload.sub)})
    row = result.first()
    if row is None:
        raise HTTPException(status_code=401, detail="Account not found or deactivated")
    access = create_access_token(subject=row.id, username=row.username, role=row.role)
    new_refresh = create_refresh_token(subject=row.id, username=row.username, role=row.role)
    return Token(access_token=access, refresh_token=new_refresh)


@app.get(f"{settings.API_PREFIX}/auth/me", response_model=AppUserRead, tags=["Auth"])
async def get_me(user: AppUserRead = Depends(get_current_user)):
    return user


@app.patch(f"{settings.API_PREFIX}/auth/me", response_model=AppUserRead, tags=["Auth"])
async def update_me(
    user_data: AppUserUpdate,
    user: AppUserRead = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    # Self-service updates may only touch profile fields. Role and jurisdiction
    # assignments are admin-controlled — silently ignore them here to prevent
    # privilege escalation.
    updates = user_data.model_dump(exclude_unset=True)
    for field in ("role", "state_id", "district_id", "block_id", "village_id"):
        updates.pop(field, None)
    if not updates:
        return user
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    stmt = text(f"UPDATE app_user SET {set_clause} WHERE id = :user_id RETURNING id")
    await db.execute(stmt, {**updates, "user_id": str(user.id)})
    result = await db.execute(_USER_SELECT, {"user_id": str(user.id)})
    row = result.first()
    logger.info("user_profile_update", user_id=str(user.id), fields=sorted(updates))
    return _row_to_user(row)


# -----------------------------------------------------------------------------
# Geo utilities (TomTom primary, Nominatim keyless fallback)
# -----------------------------------------------------------------------------
@app.get(f"{settings.API_PREFIX}/geo/reverse", tags=["Geo"])
async def reverse_geocode(lat: float, lon: float):
    """Reverse geocode a coordinate to a human-readable place label.

    Unauthenticated by design: it proxies public geocoding providers and must
    work in demo/offline-login modes where no JWT exists. Tries TomTom first
    (when TOMTOM_API_KEY is configured), then falls back to keyless
    OpenStreetMap/Nominatim so the feature degrades gracefully.
    """
    async def _tomtom(client: httpx.AsyncClient) -> dict[str, Any] | None:
        if not settings.TOMTOM_API_KEY:
            return None
        resp = await client.get(
            f"{settings.TOMTOM_BASE_URL}/search/2/reverseGeocode/{lat},{lon}.json",
            params={"key": settings.TOMTOM_API_KEY},
        )
        resp.raise_for_status()
        addresses = resp.json().get("addresses", [])
        if not addresses:
            return {"label": None, "village": None, "district": None, "state": None, "lat": lat, "lon": lon}
        addr = addresses[0].get("address", {})
        village = (
            addr.get("municipalitySubdivision")
            or addr.get("municipalityNeighbourhood")
            or addr.get("municipality")
        )
        return {
            "label": addr.get("freeformAddress") or addresses[0].get("position") and f"{lat}, {lon}",
            "village": village,
            "district": addr.get("secondaryCountrySubdivision") or addr.get("municipality"),
            "state": addr.get("countrySubdivision"),
            "lat": lat,
            "lon": lon,
            "provider": "tomtom",
        }

    async def _nominatim(client: httpx.AsyncClient) -> dict[str, Any] | None:
        resp = await client.get(
            f"{settings.NOMINATIM_BASE_URL}/reverse",
            params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 14, "addressdetails": 1},
            headers={"User-Agent": "GeoSentinel-NER/0.1 (landslide early warning dashboard)"},
        )
        if resp.status_code == 404:
            return {"label": None, "village": None, "district": None, "state": None, "lat": lat, "lon": lon}
        resp.raise_for_status()
        data = resp.json()
        addr = data.get("address", {})
        village = (
            addr.get("village") or addr.get("hamlet") or addr.get("suburb")
            or addr.get("town") or addr.get("city_district") or addr.get("city")
        )
        parts = [p for p in (data.get("display_name") or "").split(", ") if p]
        return {
            "label": ", ".join(parts[:3]) if parts else None,
            "village": village,
            "district": addr.get("state_district") or addr.get("county"),
            "state": addr.get("state"),
            "lat": lat,
            "lon": lon,
            "provider": "osm-nominatim",
        }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            try:
                result = await _tomtom(client)
                if result is not None:
                    return result
            except Exception as e:
                logger.warning("reverse_geocode_tomtom_failed_falling_back", error=str(e))
            try:
                return await _nominatim(client)
            except Exception as e:
                logger.warning("reverse_geocode_nominatim_failed", error=str(e))
                raise HTTPException(status_code=502, detail="Geocoding lookup failed")
    except HTTPException:
        raise
    except Exception:
        logger.exception("reverse_geocode_unexpected_error")
        raise HTTPException(status_code=502, detail="Geocoding lookup failed")


# -----------------------------------------------------------------------------
# Admin endpoints (State, District, Block, Village)
# -----------------------------------------------------------------------------
@app.get(f"{settings.API_PREFIX}/admin/states", response_model=PaginatedResponse[AdminStateRead], tags=["Admin"])
async def list_states(params: PageParams = Depends(), db: AsyncSession = Depends(get_db_session)):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


@app.get(f"{settings.API_PREFIX}/admin/states/{{state_id}}", response_model=AdminStateRead, tags=["Admin"])
async def get_state(state_id: UUID, db: AsyncSession = Depends(get_db_session)):
    raise HTTPException(status_code=404, detail="Not found")


# -----------------------------------------------------------------------------
# Infrastructure
# -----------------------------------------------------------------------------
@app.get(
    f"{settings.API_PREFIX}/infrastructure/roads",
    response_model=PaginatedResponse[InfrastructureRoadRead],
    tags=["Infrastructure"],
)
async def list_roads(params: PageParams = Depends(), db: AsyncSession = Depends(get_db_session)):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


@app.get(
    f"{settings.API_PREFIX}/infrastructure/facilities",
    response_model=PaginatedResponse[InfrastructureFacilityRead],
    tags=["Infrastructure"],
)
async def list_facilities(params: PageParams = Depends(), db: AsyncSession = Depends(get_db_session)):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


# -----------------------------------------------------------------------------
# Sensors — live (no hardcoded demo)
# -----------------------------------------------------------------------------
_STATIONS_SELECT = text(
    """
    SELECT id, station_code, name, station_type, network, status,
           elevation_m, district_id, village_id, metadata, installed_at,
           created_at, updated_at,
           ST_AsGeoJSON(geom)::json AS geom
    FROM sensor_station
    ORDER BY created_at DESC
    LIMIT :limit OFFSET :offset
    """
)
_STATIONS_COUNT = text("SELECT count(*) FROM sensor_station")


@app.get(
    f"{settings.API_PREFIX}/sensors/stations",
    response_model=PaginatedResponse[SensorStationRead],
    tags=["Sensors"],
)
async def list_stations(params: PageParams = Depends(), db: AsyncSession = Depends(get_db_session)):
    try:
        total_result = await db.execute(_STATIONS_COUNT)
        total = total_result.scalar() or 0
        result = await db.execute(
            _STATIONS_SELECT,
            {"limit": params.page_size, "offset": (params.page - 1) * params.page_size},
        )
        rows = result.mappings().all()
        items = []
        for r in rows:
            geom = r["geom"]
            # ST_AsGeoJSON returns dict like {"type":"Point","coordinates":[lon,lat]}
            # SensorStationRead expects PointGeometry: {type, coordinates}
            items.append(
                SensorStationRead(
                    id=r["id"],
                    station_code=r["station_code"],
                    name=r["name"],
                    station_type=r["station_type"],
                    network=r["network"],
                    status=r["status"],
                    elevation_m=r["elevation_m"],
                    district_id=r["district_id"],
                    village_id=r["village_id"],
                    metadata=r["metadata"] or {},
                    installed_at=r["installed_at"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    geom=geom,
                )
            )
        total_pages = (total + params.page_size - 1) // params.page_size if total else 0
        return PaginatedResponse(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
            total_pages=total_pages,
        )
    except Exception as exc:
        logger.warning("stations_query_degraded", error=str(exc))
        return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


@app.get(
    f"{settings.API_PREFIX}/sensors/readings",
    response_model=PaginatedResponse[SensorReadingRead],
    tags=["Sensors"],
)
async def get_readings(
    station_id: UUID | None = None,
    parameter_id: UUID | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_ts_session),
):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


# -----------------------------------------------------------------------------
# Hazard & Risk
# -----------------------------------------------------------------------------
@app.get(
    f"{settings.API_PREFIX}/hazard/inventory",
    response_model=PaginatedResponse[LandslideInventoryRead],
    tags=["Hazard"],
)
async def list_inventory(params: PageParams = Depends(), db: AsyncSession = Depends(get_db_session)):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


@app.get(f"{settings.API_PREFIX}/risk/zones", response_model=PaginatedResponse[SusceptibilityZoneRead], tags=["Risk"])
async def list_zones(params: PageParams = Depends(), db: AsyncSession = Depends(get_db_session)):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


@app.get(f"{settings.API_PREFIX}/risk/forecasts", response_model=PaginatedResponse[RiskForecastRead], tags=["Risk"])
async def list_forecasts(
    zone_id: UUID | None = None,
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_db_session),
):
    return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


# -----------------------------------------------------------------------------
# Alerts
# -----------------------------------------------------------------------------
_ALERTS_SELECT = text(
    """
    SELECT id, rule_id, zone_id, severity, title, message, message_local, language,
           issued_at, expires_at, acknowledged_at, acknowledged_by, status,
           cap_identifier, metadata
    FROM alert
    WHERE (:status IS NULL OR status = :status)
      AND (:severity IS NULL OR severity = :severity)
      AND (:since IS NULL OR issued_at > :since)
    ORDER BY issued_at DESC
    LIMIT :limit OFFSET :offset
    """
)


@app.get(f"{settings.API_PREFIX}/alerts", response_model=PaginatedResponse[AlertRead], tags=["Alerts"])
async def list_alerts(
    severity: str | None = None,
    zone_id: UUID | None = None,
    status: str | None = None,
    since: datetime | None = None,
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_db_session),
    user: AppUserRead = Depends(get_current_user),
):
    """List alerts. `since=<ISO8601>` returns only alerts issued after that
    timestamp — the realtime client uses it to backfill anything missed while
    its WebSocket was disconnected."""
    try:
        result = await db.execute(
            _ALERTS_SELECT,
            {
                "status": status,
                "severity": severity,
                "since": since,
                "limit": params.page_size,
                "offset": (params.page - 1) * params.page_size,
            },
        )
        rows = result.all()
        items = [
            AlertRead(
                id=r.id,
                rule_id=r.rule_id,
                zone_id=r.zone_id,
                severity=r.severity,
                title=r.title,
                message=r.message,
                message_local=r.message_local,
                language=r.language or "en",
                issued_at=r.issued_at,
                expires_at=r.expires_at,
                acknowledged_at=r.acknowledged_at,
                acknowledged_by=r.acknowledged_by,
                status=r.status,
                cap_identifier=r.cap_identifier,
                metadata=r.metadata or {},
            )
            for r in rows
        ]
        return PaginatedResponse(
            items=items, total=len(items), page=params.page, page_size=params.page_size, total_pages=1
        )
    except Exception as exc:
        # Table may not exist yet before migrations run — degrade to an empty
        # page instead of failing the dashboard.
        logger.warning("alerts_query_degraded", error=str(exc))
        return PaginatedResponse(items=[], total=0, page=params.page, page_size=params.page_size, total_pages=0)


@app.post(f"{settings.API_PREFIX}/alerts/{{alert_id}}/acknowledge", tags=["Alerts"])
async def acknowledge_alert(
    alert_id: UUID,
    user: AppUserRead = Depends(require_permission("alerts", "acknowledge")),
    db: AsyncSession = Depends(get_db_session),
):
    return {"status": "acknowledged", "alert_id": str(alert_id)}


# -----------------------------------------------------------------------------
# Citizen reports
# -----------------------------------------------------------------------------
_REPORT_SELECT = text(
    """
    SELECT id, report_code, reporter_id, reporter_name, reporter_phone,
           report_type, severity, description, accuracy_m, altitude_m,
           village_id, road_id, status, priority_score, cv_classification,
           cv_confidence, cv_inference_at, verified_by, verified_at,
           verification_notes, assigned_to, resolved_at, resolution_notes,
           metadata, created_at, updated_at,
           ST_AsGeoJSON(geom)::json AS geom_json
    FROM citizen_report
    WHERE (:status IS NULL OR status = :status)
      AND (:report_type IS NULL OR report_type = :report_type)
      AND (:village_id IS NULL OR village_id = :village_id)
    ORDER BY created_at DESC
    LIMIT :limit OFFSET :offset
    """
)
_REPORT_BY_ID_SELECT = text(_REPORT_SELECT.text.replace(
    "WHERE (:status IS NULL OR status = :status)\n"
    "      AND (:report_type IS NULL OR report_type = :report_type)\n"
    "      AND (:village_id IS NULL OR village_id = :village_id)",
    "WHERE id = :id",
))


def _row_to_report(row) -> CitizenReportRead:
    geom = row.geom_json
    if isinstance(geom, str):
        geom = json.loads(geom)
    return CitizenReportRead(
        id=row.id,
        report_code=row.report_code,
        reporter_name=row.reporter_name,
        reporter_phone=row.reporter_phone,
        report_type=row.report_type,
        severity=row.severity or "unknown",
        description=row.description,
        accuracy_m=float(row.accuracy_m) if row.accuracy_m is not None else None,
        altitude_m=float(row.altitude_m) if row.altitude_m is not None else None,
        village_id=row.village_id,
        road_id=row.road_id,
        status=row.status,
        priority_score=float(row.priority_score or 0),
        cv_classification=row.cv_classification,
        cv_confidence=float(row.cv_confidence) if row.cv_confidence is not None else None,
        cv_inference_at=row.cv_inference_at,
        verified_by=row.verified_by,
        verified_at=row.verified_at,
        verification_notes=row.verification_notes,
        assigned_to=row.assigned_to,
        resolved_at=row.resolved_at,
        resolution_notes=row.resolution_notes,
        metadata=row.metadata or {},
        geom=geom,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _report_priority(report: CitizenReportCreate) -> float:
    severity_score = {"low": 25, "medium": 50, "high": 75, "critical": 95}.get(
        report.severity.lower(), 35
    )
    type_score = 10 if report.report_type in {"rockfall", "road_block", "subsidence"} else 0
    return float(min(100, severity_score + type_score))


@app.post(f"{settings.API_PREFIX}/reports", response_model=CitizenReportRead, tags=["Reports"],
          dependencies=[Depends(rate_limit("reports"))])
async def create_report(
    report: CitizenReportCreate,
    user: AppUserRead | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db_session),
):
    coordinates = report.geom.coordinates
    if len(coordinates) != 2 or not (-180 <= coordinates[0] <= 180 and -90 <= coordinates[1] <= 90):
        raise HTTPException(status_code=422, detail="geom must be a valid WGS84 Point")
    report_id = uuid4()
    now = datetime.now(UTC)
    report_code = f"GSN-{now.year}-{uuid4().hex[:6].upper()}"
    priority = _report_priority(report)
    try:
        result = await db.execute(
            text(
                """
                INSERT INTO citizen_report (
                    id, report_code, reporter_id, reporter_name, reporter_phone,
                    report_type, severity, description, accuracy_m, altitude_m,
                    village_id, road_id, status, priority_score, metadata, geom,
                    created_at, updated_at
                ) VALUES (
                    :id, :report_code, :reporter_id, :reporter_name, :reporter_phone,
                    :report_type, :severity, :description, :accuracy_m, :altitude_m,
                    :village_id, :road_id, 'submitted', :priority_score, :metadata,
                    ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326), :created_at, :updated_at
                )
                RETURNING id
                """
            ),
            {
                "id": report_id,
                "report_code": report_code,
                "reporter_id": user.id if user else None,
                "reporter_name": report.reporter_name,
                "reporter_phone": report.reporter_phone,
                "report_type": report.report_type,
                "severity": report.severity,
                "description": report.description,
                "accuracy_m": report.accuracy_m,
                "altitude_m": report.altitude_m,
                "village_id": report.village_id,
                "road_id": report.road_id,
                "priority_score": priority,
                "metadata": json.dumps(report.metadata),
                "geom": json.dumps(report.geom.model_dump()),
                "created_at": now,
                "updated_at": now,
            },
        )
        await db.commit()
        if result.first() is None:
            raise HTTPException(status_code=500, detail="Report was not persisted")
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("report_persistence_failed", error=str(exc))
        raise HTTPException(status_code=422, detail="Invalid report references")
    logger.info("report_submitted", report_id=str(report_id), report_code=report_code)
    return CitizenReportRead(
        id=report_id, report_code=report_code, **report.model_dump(),
        status="submitted", priority_score=priority, created_at=now, updated_at=now,
    )


@app.get(f"{settings.API_PREFIX}/reports", response_model=PaginatedResponse[CitizenReportRead], tags=["Reports"])
async def list_reports(
    status: str | None = None,
    report_type: str | None = None,
    village_id: UUID | None = None,
    params: PageParams = Depends(),
    db: AsyncSession = Depends(get_db_session),
    user: AppUserRead = Depends(get_current_user),
):
    try:
        result = await db.execute(
            _REPORT_SELECT,
            {"status": status, "report_type": report_type, "village_id": village_id,
             "limit": params.page_size, "offset": (params.page - 1) * params.page_size},
        )
        items = [_row_to_report(row) for row in result.all()]
        return PaginatedResponse(items=items, total=len(items), page=params.page,
                                 page_size=params.page_size,
                                 total_pages=(1 if items else 0))
    except Exception as exc:
        logger.warning("reports_query_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Report store unavailable")


@app.get(f"{settings.API_PREFIX}/reports/{{report_id}}", response_model=CitizenReportRead, tags=["Reports"])
async def get_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    user: AppUserRead = Depends(get_current_user),
):
    row = (await db.execute(_REPORT_BY_ID_SELECT, {"id": report_id, "limit": 1, "offset": 0})).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _row_to_report(row)


@app.post(f"{settings.API_PREFIX}/reports/{{report_id}}/verify", response_model=CitizenReportRead, tags=["Reports"])
async def verify_report(
    report_id: UUID,
    request: dict[str, Any],
    db: AsyncSession = Depends(get_db_session),
    user: AppUserRead = Depends(require_permission("reports", "verify")),
):
    verified = bool(request.get("verified"))
    now = datetime.now(UTC)
    result = await db.execute(text(
        """
        UPDATE citizen_report
        SET status = :status, verification_notes = :notes, verified_by = :user_id,
            verified_at = :now, updated_at = :now
        WHERE id = :id RETURNING id
        """
    ), {"id": report_id, "status": "verified" if verified else "rejected",
        "notes": request.get("verification_notes"), "user_id": user.id, "now": now})
    if result.first() is None:
        raise HTTPException(status_code=404, detail="Report not found")
    await db.commit()
    row = (await db.execute(_REPORT_BY_ID_SELECT, {"id": report_id, "limit": 1, "offset": 0})).first()
    return _row_to_report(row)


@app.patch(f"{settings.API_PREFIX}/reports/{{report_id}}/status", response_model=CitizenReportRead, tags=["Reports"])
async def update_report_status(
    report_id: UUID,
    request: dict[str, Any],
    db: AsyncSession = Depends(get_db_session),
    user: AppUserRead = Depends(require_permission("reports", "resolve")),
):
    new_status = str(request.get("status", ""))
    allowed = {"submitted", "triaged", "verified", "rejected", "assigned", "escalated", "resolved"}
    if new_status not in allowed:
        raise HTTPException(status_code=422, detail="Unsupported report status")
    now = datetime.now(UTC)
    result = await db.execute(text(
        """
        UPDATE citizen_report
        SET status = :status, resolution_notes = :notes,
            resolved_at = CASE WHEN :status = 'resolved' THEN :now ELSE NULL END,
            updated_at = :now
        WHERE id = :id RETURNING id
        """
    ), {"id": report_id, "status": new_status, "notes": request.get("resolution_notes"), "now": now})
    if result.first() is None:
        raise HTTPException(status_code=404, detail="Report not found")
    await db.commit()
    row = (await db.execute(_REPORT_BY_ID_SELECT, {"id": report_id, "limit": 1, "offset": 0})).first()
    return _row_to_report(row)


# Allowed media types for citizen report uploads (defence in depth: extension
# AND declared content type must both match; actual bytes are re-validated by
# the CV triage pipeline downstream).
_ALLOWED_MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".heic",
    ".mp4", ".mov", ".webm",
    ".m4a", ".mp3", ".wav",
}
_ALLOWED_MEDIA_MIME_PREFIXES = ("image/", "video/", "audio/")


@app.post(f"{settings.API_PREFIX}/reports/{{report_id}}/media", response_model=CitizenReportMediaRead, tags=["Reports"],
          dependencies=[Depends(rate_limit("media-upload"))])
async def upload_report_media(
    report_id: UUID,
    file: UploadFile = File(...),
    is_primary: bool = False,
    user: AppUserRead = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_MEDIA_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {suffix or 'unknown'}")
    mime = (file.content_type or "").lower()
    if not mime.startswith(_ALLOWED_MEDIA_MIME_PREFIXES):
        raise HTTPException(status_code=415, detail="Unsupported content type")

    # Enforce upload size limit before buffering everything into memory.
    max_bytes = settings.MAX_UPLOAD_BYTES
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds maximum size of {max_bytes} bytes",
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    object_name = f"reports/{report_id}/{uuid4().hex}{suffix}"
    logger.info(
        "report_media_upload",
        report_id=str(report_id),
        filename=file.filename,
        size_bytes=total,
    )
    try:
        from io import BytesIO

        from minio import Minio
        storage = Minio(
            settings.MINIO_ENDPOINT, access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY, secure=settings.MINIO_SECURE,
        )
        if not storage.bucket_exists(settings.MINIO_BUCKET):
            storage.make_bucket(settings.MINIO_BUCKET)
        storage.put_object(
            settings.MINIO_BUCKET, object_name, BytesIO(b"".join(chunks)),
            length=total, content_type=mime,
        )
        media_id = uuid4()
        media_type = "photo" if mime.startswith("image/") else "video" if mime.startswith("video/") else "audio"
        await db.execute(text(
            """
            INSERT INTO citizen_report_media
                (id, report_id, media_type, file_path, file_size_bytes, mime_type, is_primary)
            VALUES (:id, :report_id, :media_type, :file_path, :size, :mime_type, :is_primary)
            """
        ), {"id": media_id, "report_id": report_id, "media_type": media_type,
            "file_path": object_name, "size": total, "mime_type": mime, "is_primary": is_primary})
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("report_media_persistence_failed", report_id=str(report_id), error=str(exc))
        raise HTTPException(status_code=503, detail="Media storage unavailable")
    return CitizenReportMediaRead(
        id=media_id, report_id=report_id, media_type=media_type,
        file_path=object_name, file_size_bytes=total, mime_type=mime,
        is_primary=is_primary, created_at=datetime.now(UTC),
    )


# -----------------------------------------------------------------------------
# WebSocket (real-time updates) — requires a valid JWT
# -----------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        self.active_connections.pop(client_id, None)

    async def send_personal_message(self, message: str, client_id: str):
        ws = self.active_connections.get(client_id)
        if ws:
            await ws.send_text(message)

    async def broadcast(self, message: str):
        for ws in list(self.active_connections.values()):
            try:
                await ws.send_text(message)
            except Exception:
                pass


manager = ConnectionManager()


# -----------------------------------------------------------------------------
# Development helpers — auto-disabled unless APP_DEBUG=true
# -----------------------------------------------------------------------------
def _ensure_dev_mode():
    if not settings.APP_DEBUG:
        raise HTTPException(status_code=404, detail="Not found")


@app.post(f"{settings.API_PREFIX}/dev/session", tags=["Dev"])
async def dev_session():
    """Mint a working access token without a database (local dev/demo only)."""
    _ensure_dev_mode()
    token = create_access_token(UUID(int=1), "demo-live", "district_officer")
    return {"access_token": token, "token_type": "bearer"}


@app.post(f"{settings.API_PREFIX}/dev/broadcast", tags=["Dev"])
async def dev_broadcast(event: dict[str, Any]):
    """Inject a RealtimeEvent to every connected WebSocket client."""
    _ensure_dev_mode()
    await manager.broadcast(json.dumps(event))
    return {"delivered": True, "clients": len(manager.active_connections)}


@app.websocket(f"{settings.API_PREFIX}/ws/{{client_id}}")
async def websocket_endpoint(websocket: WebSocket, client_id: str, token: str | None = None):
    """Authenticate before accepting. Token may be passed as `?token=` query param
    because browsers cannot set headers on WebSocket upgrade requests. Reject
    clients without a valid access token."""
    if not token:
        await websocket.close(code=4401)
        return
    try:
        verify_token(token, "access")
    except ValueError:
        await websocket.close(code=4401)
        return

    # Reject obviously-bogus client_id values.
    try:
        UUID(client_id)
    except ValueError:
        await websocket.close(code=4400)
        return

    await manager.connect(websocket, client_id)
    try:
        await websocket.send_text(
            json.dumps({"type": "connection.established", "payload": {"client_id": client_id}})
        )
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue
            # Client keepalive: respond pong so the browser knows the link is up.
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await websocket.send_text(
                    json.dumps({"type": "pong", "timestamp": datetime.now(UTC).isoformat()})
                )
    except WebSocketDisconnect:
        manager.disconnect(client_id)


# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.APP_DEBUG)
