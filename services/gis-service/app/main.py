"""
GeoSentinel-NER GIS Service
Spatial queries, vector tile serving, and map data APIs.
"""
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from geosentinel_shared import (
    close_db,
    configure_logging,
    get_db_session,
    get_logger,
    init_db,
    settings,
)
from pydantic import BaseModel, Field

configure_logging()
logger = get_logger(__name__)


# -----------------------------------------------------------------------------
# Request/Response Schemas
# -----------------------------------------------------------------------------
class TileRequest(BaseModel):
    z: int = Field(..., ge=0, le=22)
    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)
    layer: str = "risk_zones"


class SpatialQueryRequest(BaseModel):
    geom: Dict[str, Any]  # GeoJSON geometry
    layers: List[str] = ["risk_zones", "roads", "villages", "facilities"]
    buffer_m: float = 0


class SpatialQueryResponse(BaseModel):
    features: List[Dict[str, Any]]
    total: int


class RiskHeatmapRequest(BaseModel):
    bbox: List[float]  # [minx, miny, maxx, maxy]
    width: int = 512
    height: int = 512
    time: Optional[str] = None  # ISO timestamp for forecast


class DistrictRiskSummary(BaseModel):
    district_id: UUID
    district_name: str
    total_zones: int
    very_high: int
    high: int
    moderate: int
    low: int
    very_low: int
    max_risk_score: float
    population_at_risk: int


class RoadConnectivityResponse(BaseModel):
    road_id: UUID
    name: Optional[str]
    road_type: str
    condition: str
    is_critical: bool
    affected_segments: List[Dict[str, Any]]  # GeoJSON with risk overlap


# -----------------------------------------------------------------------------
# FastAPI App
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting_gis_service")
    await init_db()
    yield
    logger.info("shutting_down_gis_service")
    await close_db()


app = FastAPI(
    title="GeoSentinel-NER GIS Service",
    description="Spatial data API and vector tile server",
    version="0.1.0",
    docs_url="/docs" if settings.APP_DEBUG else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.APP_DEBUG else None,
    lifespan=lifespan,
)


# -----------------------------------------------------------------------------
# Vector Tile Endpoints (MVT)
# -----------------------------------------------------------------------------
@app.get("/tiles/{layer}/{z}/{x}/{y}.mvt")
async def get_vector_tile(
    layer: str,
    z: int,
    x: int,
    y: int,
    db=Depends(get_db_session),
):
    """Serve Mapbox Vector Tiles for map layers."""
    # In production: query PostGIS, generate MVT using asyncpg + mapbox-vector-tile
    # For now, return empty tile
    from mapbox_vector_tile import encode
    tile_data = encode({layer: []}, quantize_bounds=(x * 4096, y * 4096, (x + 1) * 4096, (y + 1) * 4096))
    return Response(content=tile_data, media_type="application/vnd.mapbox-vector-tile")


@app.get("/tiles/{layer}/{z}/{x}/{y}.pbf")
async def get_pbf_tile(
    layer: str,
    z: int,
    x: int,
    y: int,
    db=Depends(get_db_session),
):
    """Alias for .mvt"""
    return await get_vector_tile(layer, z, x, y, db)


# -----------------------------------------------------------------------------
# Raster Tile Endpoints (via TiTiler proxy)
# -----------------------------------------------------------------------------
@app.get("/raster/{dataset}/{z}/{x}/{y}.png")
async def get_raster_tile(
    dataset: str,  # e.g., "sentinel2", "dem", "risk_heatmap"
    z: int,
    x: int,
    y: int,
    time: Optional[str] = None,
):
    """Proxy to TiTiler for raster tiles."""
    # In production: proxy to TiTiler service
    # import httpx
    # async with httpx.AsyncClient() as client:
    #     resp = await client.get(f"{settings.TILE_SERVER_URL}/raster/{dataset}/{z}/{x}/{y}.png", params={"time": time})
    #     return StreamingResponse(resp.aiter_bytes(), media_type="image/png")
    raise HTTPException(status_code=501, detail="Proxy to TiTiler not implemented")


# -----------------------------------------------------------------------------
# Spatial Query Endpoints
# -----------------------------------------------------------------------------
@app.post("/query", response_model=SpatialQueryResponse)
async def spatial_query(request: SpatialQueryRequest, db=Depends(get_db_session)):
    """Query features intersecting a geometry."""
    # In production: use PostGIS ST_Intersects with buffer
    # SELECT * FROM layer WHERE ST_Intersects(geom, ST_Buffer(ST_GeomFromGeoJSON(:geom), :buffer))
    return SpatialQueryResponse(features=[], total=0)


@app.get("/risk/heatmap")
async def get_risk_heatmap(
    bbox: str = Query(..., description="minx,miny,maxx,maxy"),
    width: int = 512,
    height: int = 512,
    time: Optional[str] = None,
):
    """Generate risk heatmap image for a bounding box."""
    # In production: query risk forecasts, render heatmap
    return {"message": "Heatmap generation not implemented"}


@app.get("/risk/district-summary", response_model=List[DistrictRiskSummary])
async def get_district_risk_summary(
    state_id: Optional[UUID] = None,
    db=Depends(get_db_session),
):
    """Get risk summary per district."""
    # In production: aggregate risk forecasts by district
    return []


@app.get("/roads/connectivity", response_model=List[RoadConnectivityResponse])
async def get_road_connectivity(
    district_id: Optional[UUID] = None,
    risk_threshold: float = 0.6,
    db=Depends(get_db_session),
):
    """Get road connectivity status with risk overlay."""
    # In production: intersect roads with risk zones > threshold
    return []


@app.get("/villages/at-risk")
async def get_villages_at_risk(
    district_id: Optional[UUID] = None,
    risk_level: Optional[str] = None,
    min_population: int = 0,
    db=Depends(get_db_session),
):
    """Get villages at risk with population data."""
    return []


@app.get("/facilities/nearby")
async def get_nearby_facilities(
    lat: float,
    lon: float,
    radius_km: float = 10,
    facility_type: Optional[str] = None,
    db=Depends(get_db_session),
):
    """Find facilities near a point."""
    return []


# -----------------------------------------------------------------------------
# Layer Metadata
# -----------------------------------------------------------------------------
@app.get("/layers")
async def list_layers():
    """List available map layers with metadata."""
    return {
        "layers": [
            {
                "id": "risk_zones",
                "name": "Risk Zones",
                "type": "polygon",
                "minzoom": 0,
                "maxzoom": 16,
                "attributes": ["zone_id", "risk_level", "risk_score", "susceptibility_class"],
            },
            {
                "id": "roads",
                "name": "Roads",
                "type": "line",
                "minzoom": 8,
                "maxzoom": 18,
                "attributes": ["road_id", "name", "road_type", "condition", "is_critical"],
            },
            {
                "id": "villages",
                "name": "Villages",
                "type": "point",
                "minzoom": 10,
                "maxzoom": 18,
                "attributes": ["village_id", "name", "population", "is_remote"],
            },
            {
                "id": "facilities",
                "name": "Critical Facilities",
                "type": "point",
                "minzoom": 10,
                "maxzoom": 18,
                "attributes": ["facility_id", "name", "facility_type", "is_operational"],
            },
            {
                "id": "sensor_stations",
                "name": "Sensor Stations",
                "type": "point",
                "minzoom": 10,
                "maxzoom": 18,
                "attributes": ["station_id", "name", "station_type", "status"],
            },
            {
                "id": "landslide_inventory",
                "name": "Historical Landslides",
                "type": "polygon",
                "minzoom": 8,
                "maxzoom": 18,
                "attributes": ["event_id", "occurrence_date", "trigger_type", "fatalities"],
            },
            {
                "id": "citizen_reports",
                "name": "Citizen Reports",
                "type": "point",
                "minzoom": 10,
                "maxzoom": 18,
                "attributes": ["report_id", "report_type", "severity", "status", "cv_classification"],
            },
        ]
    }


@app.get("/styles/{style_name}")
async def get_map_style(style_name: str = "default"):
    """Get MapLibre style JSON."""
    styles = {
        "default": {
            "version": 8,
            "name": "GeoSentinel Default",
            "sources": {
                "geosentinel": {
                    "type": "vector",
                    "tiles": [f"{settings.TILE_SERVER_URL}/tiles/{{layer}}/{{z}}/{{x}}/{{y}}.mvt"],
                    "minzoom": 0,
                    "maxzoom": 18,
                }
            },
            "layers": [
                {
                    "id": "risk_zones_fill",
                    "type": "fill",
                    "source": "geosentinel",
                    "source-layer": "risk_zones",
                    "paint": {
                        "fill-color": [
                            "match",
                            ["get", "risk_level"],
                            "Very High", "#d73027",
                            "High", "#fc8d59",
                            "Moderate", "#ffffbf",
                            "Low", "#91cf60",
                            "Very Low", "#1a9850",
                            "#cccccc"
                        ],
                        "fill-opacity": 0.7,
                    },
                },
                {
                    "id": "roads_line",
                    "type": "line",
                    "source": "geosentinel",
                    "source-layer": "roads",
                    "paint": {
                        "line-color": [
                            "match",
                            ["get", "condition"],
                            "Blocked", "#d73027",
                            "Poor", "#fc8d59",
                            "Fair", "#ffffbf",
                            "Good", "#1a9850",
                            "#999999"
                        ],
                        "line-width": [
                            "interpolate",
                            ["linear"],
                            ["zoom"],
                            8, 1,
                            18, 4
                        ],
                    },
                },
            ],
        }
    }
    return styles.get(style_name, styles["default"])


# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8004, reload=settings.APP_DEBUG)
