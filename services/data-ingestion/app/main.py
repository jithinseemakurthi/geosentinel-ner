"""
GeoSentinel-NER Data Ingestion Service
Collectors for Open-Meteo/IMD weather, Satellite imagery, IoT sensors, Historical data.
"""
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from geosentinel_shared import (
    close_db,
    configure_logging,
    get_db_session,
    get_logger,
    get_timescale_db,
    init_db,
    settings,
)
from geosentinel_shared.districts import DISTRICT_COORDS
from pydantic import BaseModel
from sqlalchemy import text

configure_logging()
logger = get_logger(__name__)


WEATHER_SOURCE = "open-meteo"
WEATHER_PROVIDER_LABEL = "open-meteo"

# IMD publishes observed district rainfall publicly on its visualization page
# (same dataset the REST API serves behind a key). Keyless fallback source.
IMD_PUBLIC_RAINFALL_URL = "https://mausam.imd.gov.in/responsive/rainfallinformation.php"
# IMD's public GeoServer WFS — live district-wise nowcast warnings (keyless).
IMD_WFS_NOWCAST_URL = "https://reactjs.imd.gov.in/geoserver/imd/wfs"

_nc_cache: Dict[str, Any] = {"ts": 0.0, "data": []}


async def fetch_imd_nowcast() -> List[Dict[str, Any]]:
    """Fetch + normalize IMD district nowcast warnings from public WFS (cached 5 min).

    Geometry is stripped — only warning properties are returned.
    """
    import time as _time
    now = _time.time()
    if _nc_cache["data"] and now - _nc_cache["ts"] < 300:
        return _nc_cache["data"]

    params = {
        "service": "WFS", "version": "1.1.0", "request": "GetFeature",
        "typename": "imd:NowcastWarningDistrict",
        "srsname": "EPSG:4326", "outputFormat": "application/json",
    }
    async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
        resp = await client.get(IMD_WFS_NOWCAST_URL, params=params)
        resp.raise_for_status()
        fc = resp.json()

    out: List[Dict[str, Any]] = []
    for f in fc.get("features", []):
        p = dict(f.get("properties") or {})
        cats = {k: v for k, v in p.items() if k.startswith("cat") and isinstance(v, int)}
        p["alerts_total"] = sum(cats.values())
        p["cats_active"] = {k: v for k, v in cats.items() if v}
        out.append(p)
    _nc_cache["ts"] = now
    _nc_cache["data"] = out
    logger.info("imd_nowcast_fetched", features=len(out))
    return out


def district_uuid(name: str) -> UUID:
    """Deterministic UUID per district so Timescale rows are stable without FKs."""
    return uuid5(NAMESPACE_URL, f"geosentinel:district:{name}")


_DISTRICT_BY_UUID = {district_uuid(name): name for name in DISTRICT_COORDS}


# -----------------------------------------------------------------------------
# IMD Weather Collector
# -----------------------------------------------------------------------------
class IMDCollector:
    """Collect weather data from IMD APIs."""

    def __init__(self):
        self.api_key = settings.IMD_API_KEY
        self.base_url = settings.IMD_API_BASE_URL
        self.client = None  # httpx.AsyncClient

    async def fetch_district_forecast(self, district_id: UUID) -> Dict[str, Any]:
        """Fetch forecast for a district."""
        if not self.api_key:
            logger.warning("imd_api_key_not_configured")
            return {}

        # In production: call IMD API
        # Example endpoints:
        # - /district/forecast/{district_code}
        # - /nowcast/{district_code}
        # - /rainfall/{district_code}
        pass

    async def fetch_state_forecast(self, state_code: str) -> List[Dict[str, Any]]:
        """Fetch forecast for all districts in a state."""
        pass

    async def fetch_nowcast(self, lat: float, lon: float) -> Dict[str, Any]:
        """Fetch nowcast for a location."""
        pass

    async def fetch_district_rainfall(self) -> Dict[str, Any]:
        """Fetch observed district-wise rainfall from IMD's REST API.

        Endpoint (per IMD docs): GET {base}/api/v1/districtrainfall[?id=<imd_id>]
        Auth scheme is not publicly standardized — we send the key both as an
        ``x-api-key`` header and as ``api_key`` query param, retrying with the
        alternate on 401/403. Adjust here after inspecting one live response.
        """
        if not self.api_key:
            raise ValueError("IMD_API_KEY not configured")
        url = f"{self.base_url.rstrip('/')}/api/v1/districtrainfall"
        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(2):
                params = {"api_key": self.api_key} if attempt == 0 else {}
                headers = {"x-api-key": self.api_key} if attempt == 1 else {"Accept": "application/json"}
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code in (401, 403) and attempt == 0:
                    continue
                resp.raise_for_status()
                return resp.json()
        return {}

    @staticmethod
    def extract_rainfall(payload: Any, district: str) -> Optional[float]:
        """Best-effort extraction of rainfall_mm for a district from arbitrary IMD JSON."""
        target = district.lower()
        stack = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                name_vals = [str(v).lower() for k, v in node.items() if isinstance(v, str)]
                if any(target == v or target in v for v in name_vals):
                    for rk in ("rainfall", "rainfall_mm", "rain", "value", "actual"):
                        for k, v in node.items():
                            if rk in k.lower() and isinstance(v, (int, float)):
                                return float(v)
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        return None


class OpenMeteoCollector:
    """Keyless rainfall/weather collector using the free Open-Meteo API.

    Fetches 7 days of past observations + 3 days of hourly forecast in one
    call — enough to compute both M2 forecast rainfall and antecedent indices.
    """

    def __init__(self):
        self.base_url = settings.OPEN_METEO_BASE_URL
        self.past_hours = 168   # 7d antecedent window
        self.forecast_days = 3  # 72h M2 horizon

    async def fetch_forecast(self, lat: float, lon: float) -> Dict[str, Any]:
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "precipitation,temperature_2m,relative_humidity_2m,wind_speed_10m,surface_pressure",
            "past_hours": self.past_hours,
            "forecast_days": self.forecast_days,
            "timezone": "UTC",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{self.base_url}/forecast", params=params)
            resp.raise_for_status()
            return resp.json()

    async def fetch_district_forecast(self, district: str) -> Dict[str, Any]:
        """Fetch normalized hourly rows for a district.

        Returns {district, lat, lon, rows: [{time, valid_from, valid_to,
        rainfall_mm, temperature_c, humidity_pct, wind_speed_kmh, pressure_hpa}]}
        """
        coords = DISTRICT_COORDS[district]
        data = await self.fetch_forecast(coords["lat"], coords["lon"])
        h = data["hourly"]
        times = h["time"]

        def _num(key: str, i: int) -> Optional[float]:
            v = h.get(key, [None] * len(times))[i]
            return None if v is None else float(v)

        rows = []
        for i, t in enumerate(times):
            ts = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
            rows.append({
                "time": ts,
                "valid_from": ts - timedelta(hours=1),
                "valid_to": ts,
                "rainfall_mm": _num("precipitation", i) or 0.0,
                "temperature_c": _num("temperature_2m", i),
                "humidity_pct": _num("relative_humidity_2m", i),
                "wind_speed_kmh": _num("wind_speed_10m", i),
                "pressure_hpa": _num("surface_pressure", i),
            })
        return {
            "district": district,
            "lat": coords["lat"],
            "lon": coords["lon"],
            "rows": rows,
            "raw": {"hourly_units": data.get("hourly_units"), "elevation": data.get("elevation")},
        }


# -----------------------------------------------------------------------------
# Satellite Data Collector
# -----------------------------------------------------------------------------
class SatelliteCollector:
    """Collect satellite data from Sentinel Hub / Copernicus / NRSC."""

    def __init__(self):
        self.client_id = settings.SENTINEL_HUB_CLIENT_ID
        self.client_secret = settings.SENTINEL_HUB_CLIENT_SECRET
        self.nrsc_key = settings.NRSC_API_KEY

    async def fetch_sentinel1_insar(self, bbox: List[float], start_date: datetime, end_date: datetime) -> List[Dict]:
        """Fetch Sentinel-1 InSAR displacement data."""
        # In production: use sentinelhub-py or pystac-client
        pass

    async def fetch_sentinel2_optical(self, bbox: List[float], start_date: datetime, end_date: datetime) -> List[Dict]:
        """Fetch Sentinel-2 optical imagery metadata."""
        pass

    async def fetch_soil_moisture_smapp(self, bbox: List[float], date: datetime) -> Dict[str, Any]:
        """Fetch SMAP soil moisture data."""
        pass

    async def download_geotiff(self, asset_href: str, output_path: str) -> bool:
        """Download GeoTIFF asset to local/MinIO storage."""
        pass


# -----------------------------------------------------------------------------
# IoT Sensor Data Collector
# -----------------------------------------------------------------------------
class IoTCollector:
    """Collect data from IoT sensors via MQTT/HTTP."""

    def __init__(self):
        self.mqtt_broker = settings.KAFKA_BOOTSTRAP_SERVERS  # Reuse Kafka for MQTT bridge
        self.client = None

    async def start_mqtt_listener(self):
        """Start MQTT listener for sensor data."""
        pass

    async def process_sensor_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process incoming sensor payload."""
        # Validate, convert units, store in TimescaleDB
        pass


# -----------------------------------------------------------------------------
# Historical Data Loader
# -----------------------------------------------------------------------------
class HistoricalLoader:
    """Load historical landslide inventory from GSI Bhukosh, NIDM."""

    def __init__(self):
        pass

    async def load_gsi_inventory(self, file_path: str) -> int:
        """Load GSI Bhukosh landslide inventory (CSV/Shapefile)."""
        pass

    async def load_nidm_inventory(self, file_path: str) -> int:
        """Load NIDM disaster inventory."""
        pass


# -----------------------------------------------------------------------------
# Feature Engineering Pipeline
# -----------------------------------------------------------------------------
class FeaturePipeline:
    """Build ML features from raw data."""

    def __init__(self, db_session=None):
        self.db = db_session

    async def build_susceptibility_features(self, zone_ids: List[UUID]) -> Dict[str, Any]:
        """Build static features for M1 susceptibility model."""
        # DEM derivatives: slope, aspect, curvature, TWI, SPI
        # Geology, landuse, distance to roads/rivers/faults
        pass

    async def build_dynamic_features(
        self,
        zone_ids: List[UUID],
        forecast_hours: List[int],
        districts: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Real dynamic M2 features computed from the weather_forecast hypertable.

        Populated by the Open-Meteo ingestion job (source='open-meteo').
        Zone→district mapping: pass `districts` aligned with zone_ids; zones
        without a mapping fall back to the regional aggregate across districts.
        Soil moisture / InSAR remain null until those collectors are implemented.
        """
        now = datetime.now(timezone.utc)
        sql = text(
            """
            SELECT district_id::text AS did,
              SUM(rainfall_mm) FILTER (WHERE valid_from >= :now AND valid_to <= :h24)  AS f24,
              SUM(rainfall_mm) FILTER (WHERE valid_from >= :now AND valid_to <= :h48)  AS f48,
              SUM(rainfall_mm) FILTER (WHERE valid_from >= :now AND valid_to <= :h72)  AS f72,
              SUM(rainfall_mm) FILTER (WHERE valid_to   <= :now AND valid_from > :d1)  AS a1,
              SUM(rainfall_mm) FILTER (WHERE valid_to   <= :now AND valid_from > :d3)  AS a3,
              SUM(rainfall_mm) FILTER (WHERE valid_to   <= :now AND valid_from > :d7)  AS a7,
              SUM(rainfall_mm) FILTER (WHERE valid_to   <= :now AND valid_from > :d15) AS a15,
              AVG(humidity_pct) FILTER (WHERE valid_from >= :now AND valid_to <= :h24) AS hum
            FROM weather_forecast
            WHERE source = :src
            GROUP BY district_id
            """
        )
        params = {
            "now": now,
            "h24": now + timedelta(hours=24),
            "h48": now + timedelta(hours=48),
            "h72": now + timedelta(hours=72),
            "d1": now - timedelta(days=1),
            "d3": now - timedelta(days=3),
            "d7": now - timedelta(days=7),
            "d15": now - timedelta(days=15),
            "src": WEATHER_SOURCE,
        }

        by_district: Dict[str, Dict[str, Optional[float]]] = {}
        async with get_timescale_db().session() as session:
            result = await session.execute(sql, params)
            for row in result:
                by_district[row.did] = dict(row._mapping)

        def _num(v: Any) -> float:
            return float(v) if v is not None else 0.0

        def regional_mean(key: str) -> float:
            vals = [_num(r.get(key)) for r in by_district.values()] or [0.0]
            return sum(vals) / len(vals)

        out: List[Dict[str, Any]] = []
        for i, zid in enumerate(zone_ids):
            dname = districts[i] if districts and i < len(districts) else None
            if dname:
                row = by_district.get(str(district_uuid(dname)))
                source_label = dname
            else:
                row = None
                source_label = "regional-aggregate"
            def f(k: str):
                return _num(row.get(k)) if row is not None else regional_mean(k)

            horizon_map = {24: f("f24"), 48: f("f48"), 72: f("f72")}
            out.append({
                "zone_id": str(zid),
                "district": source_label,
                "forecast_rainfall_mm": {str(h): round(horizon_map.get(min(h, 72), 0.0), 2) for h in forecast_hours},
                "antecedent_rainfall_mm": {
                    "1d": round(f("a1"), 2),
                    "3d": round(f("a3"), 2),
                    "7d": round(f("a7"), 2),
                    "15d": round(f("a15"), 2),
                },
                "humidity_pct_avg_24h": round(f("hum"), 1),
                "soil_moisture_pct": None,
                "insar_velocity_mm_yr": None,
                "data_source": WEATHER_SOURCE,
            })
        return out


# -----------------------------------------------------------------------------
# Request/Response Schemas
# -----------------------------------------------------------------------------
class IngestionTriggerRequest(BaseModel):
    source: str  # weather/open-meteo, imd, sentinel1, sentinel2, smap, iot, historical
    params: Dict[str, Any] = {}


class DynamicFeaturesRequest(BaseModel):
    zone_ids: List[UUID]
    forecast_hours: List[int] = [24, 48, 72]
    districts: Optional[List[str]] = None


class IngestionStatusResponse(BaseModel):
    task_id: UUID
    source: str
    status: str  # queued, running, completed, failed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    records_processed: int = 0
    error: Optional[str] = None


# -----------------------------------------------------------------------------
# FastAPI App
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting_data_ingestion")
    await init_db()
    scheduler = None
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        scheduler.add_job(fetch_imd_forecasts_job, "interval", hours=3,
                          id="weather_fetch", next_run_time=datetime.now(timezone.utc))
        scheduler.start()
        logger.info("ingestion_scheduler_started", jobs=["weather_fetch@3h"])
    except ImportError:
        logger.warning("apscheduler_not_installed_scheduling_disabled")
    yield
    if scheduler:
        scheduler.shutdown(wait=False)
    logger.info("shutting_down_data_ingestion")
    await close_db()


app = FastAPI(
    title="GeoSentinel-NER Data Ingestion",
    description="External data collectors and feature pipeline",
    version="0.1.0",
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
    return {"status": "healthy", "service": "data-ingestion"}


async def fetch_imd_public_rainfall() -> List[Dict[str, Any]]:
    """Parse IMD's public rainfall map page (keyless observed data).

    The page embeds its amCharts dataProvider inline, one entry per district:
      {"title":"EAST KHASI HILLS","balloonText":"...Date : YYYY-MM-DD
       Departure : -96% Actual : 0.6 mm Normal : 14.8 mm..."}
    """
    import re
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(IMD_PUBLIC_RAINFALL_URL, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        html = resp.text

    entry_re = re.compile(
        r'"title"\s*:\s*"(?P<district>[A-Z][^"]+)"(?:(?!"title").)*?"balloonText"\s*:\s*"(?P<balloon>.*?)"',
        re.S,
    )
    act_re = re.compile(r'Actual\s*:\s*([\d.]+)\s*mm', re.I)
    norm_re = re.compile(r'Normal\s*:\s*([\d.]+)\s*mm', re.I)
    dep_re = re.compile(r'Departure\s*:\s*(-?\d+)\s*%')
    date_re = re.compile(r'Date\s*:\s*(\d{4}-\d{2}-\d{2})')

    out: List[Dict[str, Any]] = []
    seen = set()
    for m in entry_re.finditer(html):
        district = m.group("district").strip().title()
        if district.lower() in seen:
            continue
        balloon = m.group("balloon").replace("\\/", "/").replace("</br>", "\n")
        act = act_re.search(balloon)
        if not act:
            continue
        seen.add(district.lower())
        norm = norm_re.search(balloon)
        dep = dep_re.search(balloon)
        d = date_re.search(balloon)
        out.append({
            "district": district,
            "actual_mm": float(act.group(1)),
            "normal_mm": float(norm.group(1)) if norm else None,
            "departure_pct": int(dep.group(1)) if dep else None,
            "date": d.group(1) if d else None,
        })
    return out


@app.get("/imd/rainfall")
async def imd_public_rainfall(district: Optional[str] = None):
    """Live observed district rainfall straight from IMD's public map (no key)."""
    try:
        entries = await fetch_imd_public_rainfall()
    except Exception as e:
        logger.warning("imd_public_fetch_failed", error=str(e))
        raise HTTPException(status_code=502, detail="IMD public data unavailable")
    if district:
        want = district.lower()
        entries = [e for e in entries if want in e["district"].lower()]
    return {"source": "imd-public", "count": len(entries), "data": entries}


@app.get("/imd/nowcast")
async def imd_nowcast(district: Optional[str] = None, state: Optional[str] = None):
    """Live district-wise nowcast warnings from IMD's public GeoServer (no key)."""
    try:
        items = await fetch_imd_nowcast()
    except Exception as e:
        logger.warning("imd_nowcast_fetch_failed", error=str(e))
        raise HTTPException(status_code=502, detail="IMD nowcast unavailable")
    if district:
        want = district.lower()
        items = [i for i in items if want in str(i.get("District") or i.get("State_District", "")).lower()]
    if state:
        want_s = state.lower()
        items = [i for i in items if want_s in str(i.get("State", "")).lower()]
    return {"source": "imd-wfs", "count": len(items), "data": items}


@app.post("/ingest/trigger", response_model=IngestionStatusResponse)
async def trigger_ingestion(request: IngestionTriggerRequest, background_tasks: BackgroundTasks):
    """Manually trigger data ingestion for a source."""
    task_id = uuid4()

    if request.source in ("weather", "open-meteo"):
        background_tasks.add_task(run_weather_ingestion, task_id, request.params)
    elif request.source == "imd":
        background_tasks.add_task(run_imd_ingestion, task_id, request.params)
    elif request.source == "sentinel1":
        background_tasks.add_task(run_sentinel1_ingestion, task_id, request.params)
    elif request.source == "sentinel2":
        background_tasks.add_task(run_sentinel2_ingestion, task_id, request.params)
    elif request.source == "smap":
        background_tasks.add_task(run_smap_ingestion, task_id, request.params)
    elif request.source == "iot":
        background_tasks.add_task(run_iot_ingestion, task_id, request.params)
    elif request.source == "historical":
        background_tasks.add_task(run_historical_load, task_id, request.params)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown source: {request.source}")

    return IngestionStatusResponse(task_id=task_id, source=request.source, status="queued")


@app.get("/ingest/status/{task_id}", response_model=IngestionStatusResponse)
async def get_ingestion_status(task_id: UUID):
    """Get ingestion task status."""
    # In production: query task status from Redis/DB
    return IngestionStatusResponse(task_id=task_id, source="unknown", status="unknown")


@app.get("/weather/current/{district}")
async def current_weather(district: str):
    """Live keyless weather summary for a district (Open-Meteo, no DB)."""
    canonical = next((name for name in DISTRICT_COORDS if name.casefold() == district.casefold()), None)
    if canonical is None:
        raise HTTPException(status_code=404, detail=f"Unknown district: {district}")
    collector = OpenMeteoCollector()
    payload = await collector.fetch_district_forecast(canonical)
    now = datetime.now(timezone.utc)
    rows = payload["rows"]
    past24 = [r for r in rows if now - timedelta(hours=24) <= r["time"] <= now]
    next24 = [r for r in rows if now < r["valid_to"] <= now + timedelta(hours=24)]
    latest_obs = max(past24, key=lambda r: r["time"], default=None)
    return {
        "district": canonical,
        "source": WEATHER_PROVIDER_LABEL,
        "observed_rainfall_24h_mm": round(sum(r["rainfall_mm"] for r in past24), 2),
        "forecast_rainfall_next_24h_mm": round(sum(r["rainfall_mm"] for r in next24), 2),
        "temperature_c": latest_obs["temperature_c"] if latest_obs else None,
        "humidity_pct": latest_obs["humidity_pct"] if latest_obs else None,
        "wind_speed_kmh": latest_obs["wind_speed_kmh"] if latest_obs else None,
        "fetched_at": now.isoformat(),
    }


@app.post("/features/build/susceptibility")
async def build_susceptibility_features(zone_ids: List[UUID], db=Depends(get_db_session)):
    """Build static features for susceptibility modeling."""
    pipeline = FeaturePipeline(db)
    features = await pipeline.build_susceptibility_features(zone_ids)
    return {"zones_processed": len(zone_ids), "features": list(features.keys())}


@app.post("/features/build/dynamic")
async def build_dynamic_features(request: DynamicFeaturesRequest):
    """Build real dynamic features for M2 from stored Open-Meteo rainfall."""
    pipeline = FeaturePipeline()
    features = await pipeline.build_dynamic_features(
        request.zone_ids, request.forecast_hours, request.districts
    )
    return {"zones_processed": len(request.zone_ids), "features": features}


# -----------------------------------------------------------------------------
# Background Jobs
# -----------------------------------------------------------------------------
async def store_weather(payload: Dict[str, Any]) -> int:
    """Upsert normalized hourly rows into the weather_forecast hypertable."""
    did = str(district_uuid(payload["district"]))
    raw = json.dumps({
        "provider": WEATHER_SOURCE,
        "lat": payload["lat"],
        "lon": payload["lon"],
        **payload.get("raw", {}),
    })
    stmt = text(
        """
        INSERT INTO weather_forecast
            (time, district_id, source, forecast_type, valid_from, valid_to,
             rainfall_mm, temperature_c, humidity_pct, wind_speed_kmh, pressure_hpa, raw_response)
        VALUES (:t, :did, :src, 'short_range', :vf, :vt,
                :rain, :temp, :hum, :wind, :pres, CAST(:raw AS jsonb))
        ON CONFLICT (time, district_id, source, forecast_type) DO UPDATE SET
            rainfall_mm     = EXCLUDED.rainfall_mm,
            temperature_c   = EXCLUDED.temperature_c,
            humidity_pct    = EXCLUDED.humidity_pct,
            wind_speed_kmh  = EXCLUDED.wind_speed_kmh,
            pressure_hpa    = EXCLUDED.pressure_hpa,
            raw_response    = EXCLUDED.raw_response
        """
    )
    batch = [
        {
            "t": r["time"], "did": did, "src": WEATHER_SOURCE,
            "vf": r["valid_from"], "vt": r["valid_to"],
            "rain": r["rainfall_mm"], "temp": r["temperature_c"],
            "hum": r["humidity_pct"], "wind": r["wind_speed_kmh"],
            "pres": r["pressure_hpa"], "raw": raw,
        }
        for r in payload["rows"]
    ]
    async with get_timescale_db().session() as session:
        await session.execute(stmt, batch)
    return len(batch)


async def run_weather_ingestion(task_id: UUID, params: Dict[str, Any]):
    """Fetch + store Open-Meteo forecasts for all (or selected) districts."""
    districts = params.get("districts") or list(DISTRICT_COORDS)
    logger.info("weather_ingestion_started", task_id=task_id, provider=WEATHER_PROVIDER_LABEL, districts=districts)
    collector = OpenMeteoCollector()
    total = 0
    try:
        for name in districts:
            if name not in DISTRICT_COORDS:
                logger.warning("weather_unknown_district_skipped", district=name)
                continue
            payload = await collector.fetch_district_forecast(name)
            total += await store_weather(payload)
        logger.info("weather_ingestion_completed", task_id=task_id, records=total)
    except Exception as e:
        logger.error("weather_ingestion_failed", task_id=task_id, error=str(e))


async def store_observed_rainfall(district: str, rainfall_mm: float, raw: Dict[str, Any]) -> int:
    """Store one observed rainfall value into weather_forecast (source='imd')."""
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = text(
        """
        INSERT INTO weather_forecast
            (time, district_id, source, forecast_type, valid_from, valid_to,
             rainfall_mm, temperature_c, humidity_pct, wind_speed_kmh, pressure_hpa, raw_response)
        VALUES (:t, :did, 'imd', 'observed', :vf, :vt,
                :rain, NULL, NULL, NULL, NULL, CAST(:raw AS jsonb))
        ON CONFLICT (time, district_id, source, forecast_type) DO UPDATE SET
            rainfall_mm = EXCLUDED.rainfall_mm,
            raw_response = EXCLUDED.raw_response
        """
    )
    async with get_timescale_db().session() as session:
        await session.execute(stmt, {
            "t": now, "did": str(district_uuid(district)),
            "vf": day_start, "vt": now, "rain": rainfall_mm,
            "raw": json.dumps(raw)[:8000],
        })
    return 1


async def run_imd_ingestion(task_id: UUID, params: Dict[str, Any]):
    """Background job for IMD data ingestion.

    Provider routing: WEATHER_PROVIDER=imd + IMD_API_KEY -> real IMD observed
    rainfall; otherwise falls back to the keyless Open-Meteo pipeline so the
    M2 feature table is never stale.
    """
    logger.info("imd_ingestion_started", task_id=task_id, provider=settings.WEATHER_PROVIDER)
    if settings.WEATHER_PROVIDER != "imd" or not settings.IMD_API_KEY:
        if settings.WEATHER_PROVIDER == "imd":
            logger.warning("imd_api_key_not_configured_falling_back_open_meteo")
        await run_weather_ingestion(task_id, params)
        return

    collector = IMDCollector()
    try:
        payload = await collector.fetch_district_rainfall()
        stored = 0
        for name in (params.get("districts") or DISTRICT_COORDS):
            mm = IMDCollector.extract_rainfall(payload, name)
            if mm is not None:
                stored += await store_observed_rainfall(name, mm, {"district": name})
            else:
                logger.warning("imd_district_not_found_in_payload", district=name)
        logger.info("imd_ingestion_completed", task_id=task_id, records=stored)
    except Exception as e:
        logger.error("imd_ingestion_failed_falling_back", task_id=task_id, error=str(e))
        await run_weather_ingestion(task_id, params)


async def run_sentinel1_ingestion(task_id: UUID, params: Dict[str, Any]):
    """Background job for Sentinel-1 InSAR ingestion."""
    logger.info("sentinel1_ingestion_started", task_id=task_id)
    try:
        # Query STAC API, download InSAR products, process displacement
        logger.info("sentinel1_ingestion_completed", task_id=task_id)
    except Exception as e:
        logger.error("sentinel1_ingestion_failed", task_id=task_id, error=str(e))


async def run_sentinel2_ingestion(task_id: UUID, params: Dict[str, Any]):
    """Background job for Sentinel-2 optical ingestion."""
    logger.info("sentinel2_ingestion_started", task_id=task_id)
    pass


async def run_smap_ingestion(task_id: UUID, params: Dict[str, Any]):
    """Background job for SMAP soil moisture ingestion."""
    logger.info("smap_ingestion_started", task_id=task_id)
    pass


async def run_iot_ingestion(task_id: UUID, params: Dict[str, Any]):
    """Background job for IoT sensor data ingestion."""
    logger.info("iot_ingestion_started", task_id=task_id)
    pass


async def run_historical_load(task_id: UUID, params: Dict[str, Any]):
    """Background job for historical data loading."""
    logger.info("historical_load_started", task_id=task_id)
    pass


async def fetch_imd_forecasts_job():
    """Scheduled job: refresh weather forecasts every 3 hours (active provider)."""
    logger.info("scheduled_weather_fetch_started")
    await run_weather_ingestion(uuid4(), {})


async def fetch_satellite_data_job():
    """Scheduled job: fetch satellite data every 12 hours."""
    logger.info("scheduled_satellite_fetch_started")
    pass


# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=settings.APP_DEBUG)
