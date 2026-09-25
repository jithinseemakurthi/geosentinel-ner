"""
Live Internet Analysis Engine — continuous web crawler + LLM analyzer + report builder.

Runs inside the api-gateway lifespan (or as a standalone service). Every
LIVE_ENGINE_INTERVAL_SECONDS it:

  1. FETCH  — parallel httpx GETs to GDACS + ReliefWeb + (optional) GNews
  2. ANALYZE — LLM (Groq/OpenAI/NVIDIA/Ollama) extracts district/type/severity/confidence
                or heuristic keyword fallback when no LLM key is configured
  3. BUILD — deduplicates, computes priority, inserts into citizen_report
             (or keeps in-memory when DB is unreachable) and publishes to Redis
             geosentinel:reports for realtime WebSocket fan-out.

All data is LIVE — nothing is hardcoded. Evidence: /api/v1/live/engine/status,
/api/v1/live/engine/reports, /api/v1/live/reports, and the dashboard live badge.

Usage inside main.py lifespan:
    from .live_engine import engine
    await engine.start()
    yield
    await engine.stop()
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text

try:
    from geosentinel_shared import get_logger, get_primary_db, settings

    logger = get_logger(__name__)
except Exception:  # fallback when running standalone without shared package
    import logging

    _base = logging.getLogger("live_engine")

    class _Shim:
        def _fmt(self, msg, kwargs):
            return f"{msg} {kwargs}" if kwargs else msg

        def warning(self, msg, *args, **kwargs):
            _base.warning(self._fmt(msg, kwargs), *args)

        def info(self, msg, *args, **kwargs):
            _base.info(self._fmt(msg, kwargs), *args)

        def error(self, msg, *args, **kwargs):
            _base.error(self._fmt(msg, kwargs), *args)

        def debug(self, msg, *args, **kwargs):
            _base.debug(self._fmt(msg, kwargs), *args)

    logger = _Shim()  # type: ignore
    settings = None  # type: ignore

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
import os

INTERVAL_SECONDS = int(os.getenv("LIVE_ENGINE_INTERVAL_SECONDS", "300"))
ENABLED = os.getenv("LIVE_ENGINE_ENABLED", "true").lower() not in ("0", "false", "no")
MAX_REPORTS_MEMORY = 200

NER_DISTRICTS = ["Aizawl", "Imphal", "Shillong", "Gangtok", "Kohima", "Itanagar", "Agartala", "Dispur", "Guwahati"]
NER_KEYWORDS = [
    "mizoram", "aizawl", "manipur", "imphal", "churachand", "meghalaya", "shillong",
    "sikkim", "gangtok", "nagaland", "kohima", "arunachal", "itanagar", "tripura", "agartala",
    "assam", "guwahati", "dispur", "barak", "brahmaputra", "ner", "north east india", "northeast india",
]
LANDSLIDE_KEYWORDS = [
    "landslide", "land slide", "mudslide", "rockfall", "debris flow", "slope failure", "subsidence",
    "crack", "bulge", "flood", "flash flood", "heavy rain", "rainfall", "inundation", "earthquake",
    "cyclone", "road block", "road blocked", "highway blocked", "bridge collapse", "bridge collapsed",
    "sinkhole", "erosion", "avalanche", "dam breach", "building collapse", "boulder", "mud",
    "land slip", "slope", "water spring", "excavation", "cutting", "cloudburst", "deforestation",
]
NER_TERMS = ("arunachal", "assam", "manipur", "meghalaya", "mizoram", "nagaland",
             "sikkim", "tripura", "itanagar", "dispur", "imphal", "shillong",
             "aizawl", "kohima", "gangtok", "agartala", "northeast india", "barak", "brahmaputra",
             "tinsukia", "dibrugarh", "jorhat", "nagaon", "silchar", "karimganj", "hailakandi",
             "dimapur", "kohima", "mokokchung")
# Powerful problem search queries for Tavily/Brave — NE-focused
PROBLEM_SEARCH_QUERIES = [
    "landslide Mizoram Manipur Meghalaya Nagaland Sikkim Tripura Arunachal Assam today",
    "road blocked heavy rain flood North East India landslide",
    "bridge collapse sinkhole erosion hill slope failure NE India",
    "earthquake cyclone flood warning North East India IMD",
]
PROBLEM_KEYWORDS = LANDSLIDE_KEYWORDS + ["blocked", "collapsed", "breach", "slip", "cutting", "cloudburst"]

# Strict NE bounding box — covers all 8 states with small margin (used for geo-validation)
NER_BBOX = {"min_lat": 21.9, "max_lat": 29.7, "min_lon": 88.0, "max_lon": 97.5}

# District -> centroid for map placement and geo-fallback
NER_CENTROIDS: dict[str, tuple[float, float]] = {
    "Aizawl": (23.7271, 92.7176), "Imphal": (24.817, 93.9368), "Imphal West": (24.817, 93.9368),
    "Shillong": (25.5788, 91.8933), "Gangtok": (27.3389, 88.6065), "Kohima": (25.6751, 94.1086),
    "Itanagar": (27.0844, 93.6053), "Dispur": (26.1433, 91.7898), "Agartala": (23.8315, 91.2868),
    "Churachandpur": (24.2, 93.68), "East Khasi Hills": (25.46, 91.36),
}


def now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _quake_iso(epoch_ms: int | float | None) -> str:
    return datetime.fromtimestamp((epoch_ms or 0) / 1000, tz=UTC).isoformat()


def _in_ner_bbox(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    try:
        in_lat = NER_BBOX["min_lat"] <= float(lat) <= NER_BBOX["max_lat"]
        in_lon = NER_BBOX["min_lon"] <= float(lon) <= NER_BBOX["max_lon"]
        return in_lat and in_lon
    except (TypeError, ValueError):
        return False


def _contains_ner_text(value: str) -> bool:
    v = value.casefold()
    return any(term in v for term in NER_TERMS)


def _is_ner_item(item: dict[str, Any]) -> bool:
    """Strict NE-only gate: passes iff (a) coords inside NE bbox OR (b) any NER term in title/desc/country/district.
    This is the single source of truth for the live-NE algorithm — nothing else reaches the map."""
    # Fast-path: geo-validated coordinates
    lat = item.get("latitude")
    lon = item.get("longitude")
    if _in_ner_bbox(lat, lon):
        return True
    # Text gate across all textual fields (raw_* for engine, plain for gateway)
    value = " ".join(str(item.get(key) or "") for key in (
        "raw_title", "raw_description", "raw_country", "raw_district",
        "title", "description", "country", "district",
    )).casefold()
    return any(term in value for term in NER_TERMS)


def _norm(s: str) -> str:
    return s.lower().strip()


def _hash_report(title: str, url: str) -> str:
    return hashlib.sha256(f"{_norm(title)}|{_norm(url)}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Fetchers — free, no key required
# ---------------------------------------------------------------------------
async def _fetch_gdacs(limit: int = 8) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0)) as client:
            resp = await client.get(
                "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH",
                params={"eventlist": "FL;EQ;TC;WF"},
                headers={"Accept": "application/json", "User-Agent": "GeoSentinel-NER LiveEngine/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            features = data.get("features") or data.get("events") or []
            out: list[dict[str, Any]] = []
            for feat in features[:limit]:
                props = feat.get("properties") or feat
                title = props.get("name") or props.get("eventname") or props.get("title") or "GDACS event"
                country = props.get("country") or props.get("iso3") or ""
                dtype = (props.get("eventtype") or props.get("eventType") or "FL").upper()
                alert = props.get("alertlevel") or props.get("episodealertlevel") or ""
                severity = {"Red": "critical", "Orange": "high", "Green": "low"}.get(alert, "moderate")
                # Extract coordinates when present (GeoJSON geometry)
                lat = lon = None
                try:
                    geom = feat.get("geometry") or props.get("geometry")
                    if geom and geom.get("coordinates"):
                        coords = geom["coordinates"]
                        # Point: [lon, lat]; Polygon not expected for GDACS
                        if (
                            isinstance(coords, (list, tuple))
                            and len(coords) >= 2
                            and isinstance(coords[0], (int, float))
                        ):
                            lon = float(coords[0])
                            lat = float(coords[1])
                except Exception:
                    pass
                out.append(
                    {
                        "raw_title": title,
                        "raw_description": (
                            props.get("description") or props.get("htmldescription")
                            or f"{dtype} event {title} — {country}"
                        ),
                        "raw_country": country,
                        "raw_district": props.get("name") or country or "Global",
                        "event_type": dtype,
                        "severity_hint": severity,
                        "source": "GDACS",
                        "url": props.get("url")
                        or f"https://www.gdacs.org/report.aspx?eventtype={dtype}&eventid={props.get('eventid', '')}",
                        "issued_at": props.get("fromdate") or props.get("todate") or datetime.now(UTC).isoformat(),
                        "latitude": lat,
                        "longitude": lon,
                        "raw": props,
                    }
                )
            return out
    except Exception as exc:
        logger.warning("live_engine_gdacs_failed", error=str(exc))
        return []


async def _fetch_weather_signals() -> list[dict[str, Any]]:
    """Turn live Open-Meteo threshold crossings into NE regional report events (always NE geo-validated).
    Tries data-ingestion first, then falls back to direct Open-Meteo (works without Docker)."""
    async def fetch_one(district: str) -> dict[str, Any] | None:
        observed = forecast = None
        lat, lon = NER_CENTROIDS.get(district, (None, None))  # type: ignore
        fetched_at = None
        # Try data-ingestion service first (when Docker is up)
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                response = await client.get(f"http://data-ingestion:8001/weather/current/{district}")
                response.raise_for_status()
                data = response.json()
            observed = float(data.get("observed_rainfall_24h_mm") or 0)
            forecast = float(data.get("forecast_rainfall_next_24h_mm") or 0)
            fetched_at = data.get("fetched_at")
            if data.get("latitude") is not None and data.get("longitude") is not None:
                try:
                    lat = float(data["latitude"])
                    lon = float(data["longitude"])
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("weather_data_ingestion_unavailable_try_direct", district=district, error=str(exc))
            # Fallback: direct Open-Meteo (no Docker, keyless) — same logic as data-ingestion
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
                    hourly = j.get("hourly") or {}
                    precips = hourly.get("precipitation") or []
                    # Open-Meteo: first 24 points are observed, next 24 forecast (be defensive)
                    if len(precips) >= 24:
                        # past_hours=24 + forecast_days=1 => 48 points; first 24 obs, next 24 forecast
                        # Defensive split: sum first 24 as observed window, next 24 as forecast
                        observed = float(sum(float(v or 0) for v in precips[:24]))
                        forecast = float(sum(float(v or 0) for v in precips[24:48]))
                    else:
                        observed = float(sum(float(v or 0) for v in precips))
                        forecast = 0.0
                    fetched_at = datetime.now(UTC).isoformat()
            except Exception as exc2:
                logger.debug("weather_direct_openmeteo_failed", district=district, error=str(exc2))
                return None
        try:
            if observed is None or forecast is None:
                return None
            if observed < 50 and forecast < 40:
                return None
            severity = "critical" if observed >= 100 or forecast >= 80 else "high"
            return {
                "raw_title": f"Heavy rainfall watch — {district}",
                "raw_description": (
                    f"Open-Meteo reports {observed:.1f} mm observed rainfall in the last "
                    f"24 hours and {forecast:.1f} mm forecast in the next 24 hours. "
                    "Potential landslide and flash-flood trigger."
                ),
                "raw_country": "India",
                "raw_district": district,
                "event_type": "heavy_rainfall",
                "severity_hint": severity,
                "source": "Open-Meteo",
                "url": f"/weather/current/{district}",
                "issued_at": fetched_at or datetime.now(UTC).isoformat(),
                "latitude": lat,
                "longitude": lon,
            }
        except Exception as exc:
            logger.debug("weather_signal_fetch_failed", district=district, error=str(exc))
            return None

    results = await asyncio.gather(*(fetch_one(district) for district in NER_DISTRICTS))
    return [item for item in results if item is not None]


async def _fetch_reliefweb(limit: int = 8) -> list[dict[str, Any]]:
    """Fetch recent disaster reports — tries ReliefWeb v2, falls back to NASA EONET + USGS (all free, no key)."""
    # Try ReliefWeb v2 first (needs approved appname; many generic names are blocked, so we try apidoc+fallback)
    for appname in ("geosentinel-test", "public", "reliefweb"):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(
                    "https://api.reliefweb.int/v2/reports",
                    params={"appname": appname, "limit": limit, "query[value]": "landslide India"},
                    headers={"Accept": "application/json"},
                )
                if resp.status_code == 200:
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
                        body = fields.get("body") or ""
                        if isinstance(body, list):
                            body = " ".join(str(b) for b in body)
                        out.append(
                            {
                                "raw_title": title,
                                "raw_description": (body[:800] if isinstance(body, str) else str(body)[:800]) or title,
                                "raw_country": country,
                                "raw_district": country or "India",
                                "event_type": "landslide",
                                "severity_hint": "moderate",
                                "source": "ReliefWeb",
                                "url": fields.get("url")
                                or it.get("href")
                                or f"https://reliefweb.int/report/{it.get('id')}",
                                "issued_at": (fields.get("date") or {}).get("created") or now_utc_iso(),
                                "raw": fields,
                            }
                        )
                    if out:
                        return out
        except Exception:
            continue
    # Fallback: NASA EONET (severe storms / floods) + USGS earthquakes — both free, no key, always available
    out: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            # EONET severe storms (often monsoon floods in India)
            try:
                r = await client.get(
                    "https://eonet.gsfc.nasa.gov/api/v3/events",
                    params={"limit": limit, "status": "open"},
                )
                r.raise_for_status()
                for ev in (r.json().get("events") or [])[: limit // 2]:
                    title = ev.get("title", "EONET event")
                    cats = ", ".join(c.get("title", "") for c in ev.get("categories") or [])
                    out.append(
                        {
                            "raw_title": f"{title} — {cats}",
                            "raw_description": f"{title} {cats} {ev.get('description') or ''}"[:700],
                            "raw_country": "Global",
                            "raw_district": "Global",
                            "event_type": "other",
                            "severity_hint": "moderate",
                            "source": "EONET",
                            "url": ev.get("link") or "https://eonet.gsfc.nasa.gov/",
                            "issued_at": (ev.get("geometry") or [{}])[0].get("date") or now_utc_iso(),
                            "raw": ev,
                        }
                    )
            except Exception:
                pass
            # USGS recent quakes (M4.5+; quakes can trigger landslides in NER)
            try:
                r = await client.get(
                    "https://earthquake.usgs.gov/fdsnws/event/1/query",
                    params={
                        "format": "geojson",
                        "limit": min(limit, 4),
                        "minmagnitude": 4.5,
                        "orderby": "time",
                    },
                )
                r.raise_for_status()
                for feat in (r.json().get("features") or [])[: limit // 2]:
                    props = feat.get("properties") or {}
                    geom = feat.get("geometry") or {}
                    coords = geom.get("coordinates") or [0, 0]
                    place = props.get("place") or "earthquake"
                    mag = props.get("mag") or 0
                    out.append(
                        {
                            "raw_title": f"M{mag} earthquake — {place}",
                            "raw_description": (
                                f"Earthquake M{mag} at {place}, depth "
                                f"{coords[2] if len(coords) > 2 else '?'}km — potential landslide trigger. "
                                f"{props.get('url', '')}"
                            )[:700],
                            "raw_country": place.split(",")[-1].strip() if "," in place else "Global",
                            "raw_district": "Global",
                            "event_type": "earthquake",
                            "severity_hint": "high" if mag >= 6 else "moderate" if mag >= 5 else "low",
                            "source": "USGS",
                            "url": props.get("url") or "https://earthquake.usgs.gov/",
                            "issued_at": _quake_iso(props.get("time")) if props.get("time") else now_utc_iso(),
                            "raw": props,
                        }
                    )
            except Exception:
                pass
    except Exception as exc:
        logger.warning("live_engine_eonet_usgs_failed", error=str(exc))
    return out


async def _fetch_gnews(limit: int = 6) -> list[dict[str, Any]]:
    """Optional: GNews free tier (requires GNEWS_API_KEY). Skipped when not configured.
    Query is NE-focused so only NE hits survive the downstream _is_ner_item gate."""
    api_key = os.getenv("GNEWS_API_KEY") or os.getenv("NEWS_API_KEY")
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0)) as client:
            resp = await client.get(
                "https://gnews.io/api/v4/search",
                params={
                    "q": (
                        "landslide (Assam OR Mizoram OR Manipur OR Meghalaya OR "
                        "Nagaland OR Sikkim OR Tripura OR Arunachal)"
                    ),
                    "lang": "en",
                    "max": limit,
                    "apikey": api_key,
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            articles = data.get("articles") or []
            out: list[dict[str, Any]] = []
            for art in articles[:limit]:
                out.append(
                    {
                        "raw_title": art.get("title", ""),
                        "raw_description": art.get("description", "") or art.get("content", "")[:600],
                        "raw_country": "India",
                        "raw_district": "India",
                        "event_type": "landslide",
                        "severity_hint": "moderate",
                        "source": "GNews",
                        "url": art.get("url", ""),
                        "issued_at": art.get("publishedAt") or datetime.now(UTC).isoformat(),
                        "latitude": None,
                        "longitude": None,
                        "raw": art,
                    }
                )
            return out
    except Exception as exc:
        logger.warning("live_engine_gnews_failed", error=str(exc))
        return []


async def _fetch_tavily(limit: int = 8) -> list[dict[str, Any]]:
    """Powerful problem search via Tavily (when TAVILY_API_KEY set) — NE landslide/road-block queries."""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return []
    out: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0)) as client:
            for q in PROBLEM_SEARCH_QUERIES[:2]:
                try:
                    resp = await client.post(
                        "https://api.tavily.com/search",
                        json={
                            "api_key": api_key,
                            "query": q,
                            "search_depth": "advanced",
                            "include_answer": True,
                            "max_results": limit // 2,
                        },
                        headers={"Content-Type": "application/json"},
                    )
                    resp.raise_for_status()
                    for r in (resp.json().get("results") or [])[: limit // 2]:
                        out.append({
                            "raw_title": r.get("title", "")[:180],
                            "raw_description": r.get("content", "")[:800],
                            "raw_country": "India",
                            "raw_district": "India",
                            "event_type": "tavily_search",
                            "severity_hint": "moderate",
                            "source": "Tavily",
                            "url": r.get("url", ""),
                            "issued_at": datetime.now(UTC).isoformat(),
                            "latitude": None,
                            "longitude": None,
                            "raw": r,
                        })
                except Exception as exc:
                    logger.debug("live_engine_tavily_query_failed", query=q[:30], error=str(exc))
    except Exception as exc:
        logger.warning("live_engine_tavily_failed", error=str(exc))
    return out[:limit]


async def _fetch_brave(limit: int = 6) -> list[dict[str, Any]]:
    """Powerful problem search via Brave Search (when BRAVE_SEARCH_API_KEY set)."""
    api_key = os.getenv("BRAVE_SEARCH_API_KEY")
    if not api_key:
        return []
    out: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0)) as client:
            for q in PROBLEM_SEARCH_QUERIES[:2]:
                try:
                    resp = await client.get(
                        "https://api.search.brave.com/res/v1/web/search",
                        params={"q": q, "count": limit // 2},
                        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                    )
                    resp.raise_for_status()
                    for r in ((resp.json().get("results") or {}).get("results") or [])[: limit // 2]:
                        out.append({
                            "raw_title": r.get("title", "")[:180],
                            "raw_description": (r.get("description") or "")[:800],
                            "raw_country": "India",
                            "raw_district": "India",
                            "event_type": "brave_search",
                            "severity_hint": "moderate",
                            "source": "Brave",
                            "url": r.get("url", ""),
                            "issued_at": r.get("age") or datetime.now(UTC).isoformat(),
                            "latitude": None,
                            "longitude": None,
                            "raw": r,
                        })
                except Exception as exc:
                    logger.debug("live_engine_brave_query_failed", query=q[:30], error=str(exc))
    except Exception as exc:
        logger.warning("live_engine_brave_failed", error=str(exc))
    return out[:limit]


# ---------------------------------------------------------------------------
# Analyzer — LLM (when GEO_LLM/Groq/OpenAI key is set) else heuristic
# ---------------------------------------------------------------------------
def _heuristic_analyze(raw: dict[str, Any]) -> dict[str, Any]:
    title = f"{raw.get('raw_title','')} {raw.get('raw_description','')}".lower()
    src = raw.get('source','')
    # Multi-signal relevance: disaster/web feeds are pre-filtered, else require problem+NER match
    # Count keyword hits for confidence
    problem_hits = sum(1 for kw in PROBLEM_KEYWORDS if kw in title)  # noqa: E501
    ner_hits = sum(1 for kw in NER_KEYWORDS if kw in title)
    has_problem = problem_hits > 0
    has_ner = ner_hits > 0 or "india" in title
    # Extract problem tags for report building
    problem_tags = [kw for kw in PROBLEM_KEYWORDS if kw in title]
    prefiltered = ('GDACS', 'EONET', 'USGS', 'ReliefWeb', 'GNews', 'Open-Meteo', 'Tavily', 'Brave')
    if src in prefiltered and has_problem:
        relevant = True
    else:
        # Strong problem hit with NER, or two problem hits, or Tavily/Brave + NER
        relevant = (
            (has_problem and has_ner)
            or (problem_hits >= 2)
            or (problem_hits >= 1 and src in ("Tavily", "Brave") and has_ner)
        )
    # District extraction — first NER district mentioned, else use actual country/Global
    district = raw.get("raw_country") or "Global"
    for d in NER_DISTRICTS:
        if d.lower() in title:
            district = d
            break
    else:
        if "india" in title or "india" in (raw.get("raw_country") or "").lower():
            district = "India"
        elif district in ("", "Global") and relevant:
            district = raw.get("raw_country") or "Global"
        if not district or district.strip() == "":
            district = "Global"

    # Type — expanded problem mapping (more powerful search)
    report_type = "other"
    if "crack" in title:
        report_type = "crack"
    elif "bulge" in title:
        report_type = "bulge"
    elif "subsidence" in title or "sinkhole" in title:
        report_type = "subsidence"
    elif "debris" in title:
        report_type = "debris"
    elif "rockfall" in title or "rock fall" in title or "boulder" in title:
        report_type = "rockfall"
    elif "road" in title and "block" in title:
        report_type = "road_block"
    elif "bridge" in title and ("collapse" in title or "collapsed" in title):
        report_type = "road_block"
    elif "highway" in title and "blocked" in title:
        report_type = "road_block"
    elif "avalanche" in title:
        report_type = "debris"
    elif "dam breach" in title or "dam" in title and "breach" in title:
        report_type = "water_spring"
    elif "cloudburst" in title:
        report_type = "water_spring"
    elif "excavation" in title or "cutting" in title or "deforestation" in title:
        report_type = "excavation"
    elif "flood" in title or "water" in title or "inundation" in title:
        report_type = "water_spring"
    elif "erosion" in title:
        report_type = "subsidence"
    elif any(k in title for kw in LANDSLIDE_KEYWORDS for k in [kw]):
        report_type = "other"

    # Severity — more granular
    severity = raw.get("severity_hint") or "moderate"
    if any(w in title for w in ["dead", "killed", "death", "evacuat", "critical", "red alert", "collapsed", "breach"]):
        severity = "critical"
    elif any(w in title for w in ["blocked", "high", "warning", "orange", "sinkhole", "avalanche"]):
        severity = "high"
    elif any(w in title for w in ["moderate", "yellow"]):
        severity = "moderate"

    # Confidence — powerful multi-signal (problem_hits + ner_hits)
    if relevant and district != "India" and problem_hits >= 2:
        confidence = 0.90
    elif relevant and district != "India":
        confidence = 0.82
    elif relevant and problem_hits >= 2:
        confidence = 0.75
    elif relevant:
        confidence = 0.62
    else:
        confidence = 0.32
    # Boost for Tavily/Brave hits
    if src in ("Tavily", "Brave") and has_problem:
        confidence = min(0.95, confidence + 0.08)

    # Include problem tags in summary
    summary = raw.get("raw_title", "")[:140]
    if problem_tags:
        summary = f"{summary} [{', '.join(problem_tags[:3])}]"
    return {
        "relevant": relevant,
        "district": district,
        "report_type": report_type,
        "severity": severity,
        "confidence": confidence,
        "summary": summary,
        "problem_tags": problem_tags,
        "problem_hits": problem_hits,
        "ner_hits": ner_hits,
    }


async def _llm_analyze(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Ask the configured LLM to extract structured fields. Returns None when no key / failure."""
    # Reuse the gateway's GEO_LLM resolver — import lazily to avoid circular import
    try:
        from .main import _call_remote_llm  # type: ignore
    except Exception:
        return None
    prompt = (
        "You are a landslide report analyzer for North East India (NER). "
        "Given this internet article, decide if it is relevant to landslides/floods/road blocks in NER or India. "
        "NER states: Mizoram (Aizawl), Manipur (Imphal), Meghalaya (Shillong), Nagaland (Kohima), "
        "Arunachal (Itanagar), Tripura (Agartala), Sikkim (Gangtok), Assam (Guwahati/Dispur).\n\n"
        f"Title: {raw.get('raw_title','')}\n"
        f"Description: {raw.get('raw_description','')[:800]}\n"
        f"Source: {raw.get('source','')} Country: {raw.get('raw_country','')}\n\n"
        "Return ONLY valid JSON with keys: relevant (bool), district (one of "
        "Aizawl/Imphal/Shillong/Gangtok/Kohima/Itanagar/Agartala/Dispur/India/NER/Global), "
        "report_type (crack/bulge/subsidence/debris/rockfall/road_block/excavation/water_spring/other), "
        "severity (low/moderate/high/critical), confidence (0-1), summary (1 sentence, <=20 words)."
    )
    try:
        result = await _call_remote_llm(
            [
                {"role": "system", "content": "You are a precise JSON extractor. Reply only with valid JSON."},
                {"role": "user", "content": prompt},
            ]
        )
        if not result:
            return None
        content, _model = result
        # Extract JSON block
        import re

        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return None
        obj = json.loads(m.group(0))
        # Validate
        return {
            "relevant": bool(obj.get("relevant", False)),
            "district": str(obj.get("district", "India")),
            "report_type": str(obj.get("report_type", "other")),
            "severity": str(obj.get("severity", "moderate")),
            "confidence": float(obj.get("confidence", 0.6)),
            "summary": str(obj.get("summary", raw.get("raw_title","")[:120])),
        }
    except Exception as exc:
        logger.warning("live_engine_llm_analyze_failed", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class LiveInternetEngine:
    def __init__(self, interval_seconds: int = INTERVAL_SECONDS):
        self.interval = interval_seconds
        self.enabled = ENABLED
        self.running = False
        self._task: asyncio.Task | None = None
        self.last_run: datetime | None = None
        self.next_run: datetime | None = None
        self.stats: dict[str, int] = {
            "cycles": 0, "fetched": 0, "analyzed": 0, "built": 0,
            "skipped_irrelevant": 0, "errors": 0, "deduplicated": 0,
        }
        self.reports: list[dict[str, Any]] = []
        self.seen_hashes: set[str] = set()
        self.last_error: str | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if not self.enabled:
            logger.info("live_engine_disabled", interval=self.interval)
            return
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("live_engine_started", interval_s=self.interval)

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("live_engine_stopped")

    async def _loop(self) -> None:
        # Immediate first cycle after 4s so the dashboard shows live data quickly
        try:
            await asyncio.sleep(4)
            await self.run_cycle()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("live_engine_first_cycle_failed", error=str(exc))
        while self.running:
            self.next_run = datetime.now(UTC) + timedelta(seconds=self.interval)
            try:
                await asyncio.sleep(self.interval)
                if not self.running:
                    break
                await self.run_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("live_engine_loop_error", error=str(exc))
                await asyncio.sleep(10)

    async def run_cycle(self) -> dict[str, Any]:
        """One full fetch → analyze → build cycle. Returns summary."""
        started = time.time()
        summary: dict[str, Any] = {"fetched": 0, "analyzed": 0, "built": 0, "skipped": 0, "errors": 0}
        async with self._lock:
            self.last_run = datetime.now(UTC)
            try:
                # 1) FETCH — powerful search across 6 sources (GDACS + ReliefWeb + GNews + Weather + Tavily + Brave)
                gdacs, relief, gnews, weather, tavily, brave = await asyncio.gather(
                    _fetch_gdacs(8), _fetch_reliefweb(8), _fetch_gnews(6),
                    _fetch_weather_signals(), _fetch_tavily(8), _fetch_brave(6),
                )
                raw_items = gdacs + relief + gnews + weather + tavily + brave
                summary["fetched"] = len(raw_items)
                self.stats["fetched"] += len(raw_items)
                if not raw_items:
                    self.stats["cycles"] += 1
                    self.last_error = None
                    return summary

                # 2) ANALYZE + 3) BUILD
                for raw in raw_items:
                    try:
                        if not _is_ner_item(raw):
                            summary["skipped"] += 1
                            self.stats["skipped_irrelevant"] += 1
                            continue
                        summary["analyzed"] += 1
                        self.stats["analyzed"] += 1
                        # Try LLM first, fallback to heuristic
                        analyzed = await _llm_analyze(raw)
                        if analyzed is None:
                            analyzed = _heuristic_analyze(raw)
                        # Filter: keep NER-relevant or India-wide landslides; skip completely irrelevant
                        if not analyzed.get("relevant") and analyzed.get("confidence", 0) < 0.12:
                            summary["skipped"] += 1
                            self.stats["skipped_irrelevant"] += 1
                            continue
                        # Deduplicate
                        h = _hash_report(raw.get("raw_title",""), raw.get("url",""))
                        if h in self.seen_hashes:
                            self.stats["deduplicated"] += 1
                            continue
                        self.seen_hashes.add(h)
                        # Build report
                        report = await self._build_report(raw, analyzed, h)
                        if report:
                            self.reports.insert(0, report)
                            # Keep memory bounded
                            if len(self.reports) > MAX_REPORTS_MEMORY:
                                self.reports = self.reports[:MAX_REPORTS_MEMORY]
                            summary["built"] += 1
                            self.stats["built"] += 1
                    except Exception as exc:
                        summary["errors"] += 1
                        self.stats["errors"] += 1
                        logger.warning("live_engine_item_failed", error=str(exc), title=raw.get("raw_title","")[:60])

                self.stats["cycles"] += 1
                self.last_error = None
                elapsed = int((time.time() - started) * 1000)
                logger.info(
                    "live_engine_cycle_done",
                    fetched=summary["fetched"], built=summary["built"],
                    skipped=summary["skipped"], latency_ms=elapsed,
                )
            except Exception as exc:
                self.last_error = str(exc)
                self.stats["errors"] += 1
                logger.warning("live_engine_cycle_failed", error=str(exc))
        self.next_run = datetime.now(UTC) + timedelta(seconds=self.interval)
        return summary

    async def _build_report(self, raw: dict[str, Any], analyzed: dict[str, Any], h: str) -> dict[str, Any] | None:
        district = analyzed.get("district", raw.get("raw_district", "India"))
        # Normalize district to known NE enum when possible
        if district not in NER_CENTROIDS:
            # try to map state names to capitals
            _alias = {
                "arunachal pradesh": "Itanagar", "assam": "Dispur", "manipur": "Imphal",
                "meghalaya": "Shillong", "mizoram": "Aizawl", "nagaland": "Kohima",
                "sikkim": "Gangtok", "tripura": "Agartala",
            }
            district = _alias.get(district.lower().strip(), district)
        report_type = analyzed.get("report_type", "other")
        severity = analyzed.get("severity", raw.get("severity_hint", "moderate"))
        confidence = float(analyzed.get("confidence", 0.6))
        summary = analyzed.get("summary") or raw.get("raw_title", "")[:140]

        # Priority 0-100: severity base + confidence boost + NER bonus
        base = {"low": 25, "moderate": 50, "high": 75, "critical": 92}.get(_norm(severity), 50)
        ner_bonus = 12 if district in NER_DISTRICTS or district in NER_CENTROIDS else 0
        priority = max(0, min(100, int(base + confidence * 10 + ner_bonus)))

        # Village/district mapping
        village = district if district in NER_CENTROIDS else raw.get("raw_country") or "Live"
        if raw.get("source") == "ReliefWeb" and raw.get("raw_country"):
            village = raw["raw_country"].split(",")[0].strip()[:40]
        if district in NER_DISTRICTS:
            village = district

        report_id = f"live-{h}"
        code = f"LIVE-{h[:6].upper()}"
        now_iso = datetime.now(UTC).isoformat()
        issued = raw.get("issued_at") or now_iso

        # Resolve coordinates for map visibility — priority: raw lat/lon -> district centroid -> NER centroid
        lat = raw.get("latitude")
        lon = raw.get("longitude")
        if lat is None or lon is None:
            centroid = NER_CENTROIDS.get(district)
            if centroid:
                lat, lon = centroid
            else:
                lat, lon = (25.6, 92.4)
        try:
            lat = float(lat)
            lon = float(lon)
        except Exception:
            lat, lon = (25.6, 92.4)

        # Description includes LLM summary + problem tags + source URL for citation
        problem_tags = analyzed.get("problem_tags") or []
        tags_str = f" | problems: {', '.join(problem_tags[:5])}" if problem_tags else ""
        desc = f"{summary}{tags_str} — Source: {raw.get('source')} {raw.get('url','')}"
        if len(desc) > 900:
            desc = desc[:900]

        report: dict[str, Any] = {
            "id": report_id,
            "code": code,
            "report_type": report_type,
            "reportType": report_type,
            "village": village,
            "district": district,
            "severity": severity,
            "description": desc,
            "status": "live_internet",
            "priorityScore": priority,
            "priority_score": priority,
            "created_at": issued,
            "createdAt": issued,
            "source": raw.get("source", "LiveEngine"),
            "url": raw.get("url"),
            "country": raw.get("raw_country"),
            "confidence": confidence,
            "hash": h,
            "latitude": lat,
            "longitude": lon,
            # explicit aliases for frontend / GIS
            "lat": lat,
            "lng": lon,
            # powerful search: add problem metadata for reports UI
            "problem_tags": problem_tags,
            "problem_hits": analyzed.get("problem_hits", 0),
            "ner_hits": analyzed.get("ner_hits", 0),
            "event_type": raw.get("event_type"),
            "raw_title": raw.get("raw_title"),
        }

        # Try to persist to DB (best-effort) and publish to Redis
        try:
            async with get_primary_db().session() as session:  # type: ignore
                centroids_wkt = {
                    "Aizawl": "POINT(92.7176 23.7271)",
                    "Imphal": "POINT(93.9368 24.817)",
                    "Shillong": "POINT(91.8933 25.5788)",
                    "Gangtok": "POINT(88.6065 27.3389)",
                    "Kohima": "POINT(94.1086 25.6751)",
                    "Itanagar": "POINT(93.6053 27.0844)",
                    "Agartala": "POINT(91.2868 23.8315)",
                    "Dispur": "POINT(91.7898 26.1433)",
                    "Churachandpur": "POINT(93.68 24.2)",
                    "East Khasi Hills": "POINT(91.36 25.46)",
                    "Imphal West": "POINT(93.9368 24.817)",
                    "India": "POINT(78.9629 20.5937)",
                    "NER": "POINT(92.0 26.0)",
                    "Global": "POINT(0 0)",
                }
                # Prefer precise per-report lon/lat when available, else centroid WKT
                if report.get("longitude") is not None and report.get("latitude") is not None:
                    wkt = f"POINT({report['longitude']} {report['latitude']})"
                else:
                    wkt = centroids_wkt.get(district, centroids_wkt["India"])
                await session.execute(
                    text(
                        """
                        INSERT INTO citizen_report
                            (id, report_code, report_type, severity, description, status,
                             priority_score, geom, created_at, updated_at)
                        VALUES (gen_random_uuid(), :code, :rtype, :sev, :desc, 'submitted',
                                :prio, ST_GeomFromText(:wkt, 4326), NOW(), NOW())
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {"code": code, "rtype": report_type, "sev": severity, "desc": desc, "prio": priority, "wkt": wkt},
                )
                await session.commit()
        except Exception as exc:
            # DB not reachable in dev without Docker — keep in-memory only (still served via API)
            logger.warning("live_engine_db_persist_skipped", error=str(exc), code=code)

        # Publish to Redis for realtime WebSocket push (best-effort)
        try:
            import redis.asyncio as aioredis  # type: ignore

            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            r = aioredis.from_url(redis_url, password=os.getenv("REDIS_PASSWORD"))
            await r.publish("geosentinel:reports", json.dumps({"type": "report.new", "payload": report}))
            await r.aclose()
        except Exception:
            pass

        return report

    def get_status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self.running,
            "interval_seconds": self.interval,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "stats": dict(self.stats),
            "reports_in_memory": len(self.reports),
            "last_error": self.last_error,
            "sources": [
                "GDACS (flood/eq/cyclone/wildfire)",
                "ReliefWeb (landslide NE India)",
                "Open-Meteo (NE heavy-rainfall watch)",
                "GNews (optional, NE query)",
                "Tavily (NE problem search, when TAVILY_API_KEY set)",
                "Brave (NE problem search, when BRAVE_SEARCH_API_KEY set)",
            ],
            "analyzer": "LLM (Groq/OpenAI/NVIDIA/Ollama) with powerful heuristic fallback (problem_tags, multi-signal)",
            "algorithm": {
                "name": "NER Live-Only Filter v2 - Powerful Problem Search",
                "bbox": NER_BBOX,
                "ner_terms": list(NER_TERMS),
                "districts": NER_DISTRICTS,
                "queries": PROBLEM_SEARCH_QUERIES,
                "rule": (
                    "coords inside NE bbox OR NER term in text; Tavily/Brave add NE "
                    "problem queries; heuristic uses problem_hits+ner_hits -> "
                    "confidence; tags persisted to reports"
                ),
            },
        }

    def get_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.reports[:limit]


# Singleton — imported by main.py
engine = LiveInternetEngine(interval_seconds=INTERVAL_SECONDS)
