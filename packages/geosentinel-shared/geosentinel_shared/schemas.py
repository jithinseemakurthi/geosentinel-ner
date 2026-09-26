"""
GeoSentinel-NER Shared Pydantic Schemas
"""
from datetime import datetime, timezone
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import mapping, shape


# -----------------------------------------------------------------------------
# Base schemas
# -----------------------------------------------------------------------------
class BaseSchema(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=True,
        json_schema_extra={"examples": []},
    )


class IDMixin(BaseSchema):
    id: UUID


class TimestampMixin(BaseSchema):
    created_at: datetime
    updated_at: Optional[datetime] = None


# -----------------------------------------------------------------------------
# Geometry handling
# -----------------------------------------------------------------------------
class GeometryBase(BaseSchema):
    type: Literal["Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"]
    coordinates: Any

    @classmethod
    def from_shapely(cls, geom) -> "GeometryBase":
        if geom is None:
            return None
        geojson_dict = mapping(geom)
        return cls(type=geojson_dict["type"], coordinates=geojson_dict["coordinates"])

    def to_shapely(self):
        return shape({"type": self.type, "coordinates": self.coordinates})


class PointGeometry(GeometryBase):
    type: Literal["Point"]
    coordinates: List[float]  # [lon, lat]


class LineStringGeometry(GeometryBase):
    type: Literal["LineString"]
    coordinates: List[List[float]]


class PolygonGeometry(GeometryBase):
    type: Literal["Polygon"]
    coordinates: List[List[List[float]]]


class MultiPolygonGeometry(GeometryBase):
    type: Literal["MultiPolygon"]
    coordinates: List[List[List[List[float]]]]


# -----------------------------------------------------------------------------
# Admin boundaries
# -----------------------------------------------------------------------------
class AdminStateBase(BaseSchema):
    code: str
    name_en: str
    name_local: Optional[str] = None


class AdminStateRead(AdminStateBase, IDMixin, TimestampMixin):
    geom: Optional[MultiPolygonGeometry] = None


class AdminDistrictBase(BaseSchema):
    state_id: UUID
    code: str
    name_en: str
    name_local: Optional[str] = None
    headquarters: Optional[str] = None
    population: Optional[int] = None


class AdminDistrictRead(AdminDistrictBase, IDMixin, TimestampMixin):
    geom: Optional[MultiPolygonGeometry] = None


class AdminBlockBase(BaseSchema):
    district_id: UUID
    code: str
    name_en: str
    name_local: Optional[str] = None


class AdminBlockRead(AdminBlockBase, IDMixin, TimestampMixin):
    geom: Optional[MultiPolygonGeometry] = None


class AdminVillageBase(BaseSchema):
    block_id: UUID
    code: str
    name_en: str
    name_local: Optional[str] = None
    population: Optional[int] = None
    households: Optional[int] = None
    is_remote: bool = False


class AdminVillageRead(AdminVillageBase, IDMixin, TimestampMixin):
    geom: Optional[PointGeometry] = None
    boundary_geom: Optional[PolygonGeometry] = None


# -----------------------------------------------------------------------------
# Infrastructure
# -----------------------------------------------------------------------------
class InfrastructureRoadBase(BaseSchema):
    name: Optional[str] = None
    road_type: Optional[str] = None
    surface_type: Optional[str] = None
    width_m: Optional[float] = None
    condition: Optional[str] = None
    is_critical: bool = False
    district_id: Optional[UUID] = None
    metadata: Dict[str, Any] = {}


class InfrastructureRoadRead(InfrastructureRoadBase, IDMixin, TimestampMixin):
    geom: Optional[LineStringGeometry] = None


class InfrastructureBridgeBase(BaseSchema):
    name: Optional[str] = None
    road_id: Optional[UUID] = None
    bridge_type: Optional[str] = None
    span_m: Optional[float] = None
    condition: Optional[str] = None


class InfrastructureBridgeRead(InfrastructureBridgeBase, IDMixin, TimestampMixin):
    geom: Optional[PointGeometry] = None


class InfrastructureFacilityBase(BaseSchema):
    name: str
    facility_type: str
    capacity: Optional[int] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    is_operational: bool = True
    district_id: Optional[UUID] = None
    metadata: Dict[str, Any] = {}


class InfrastructureFacilityRead(InfrastructureFacilityBase, IDMixin, TimestampMixin):
    geom: Optional[PointGeometry] = None


# -----------------------------------------------------------------------------
# Sensor Network
# -----------------------------------------------------------------------------
class SensorStationBase(BaseSchema):
    station_code: str
    name: Optional[str] = None
    station_type: str
    network: Optional[str] = None
    status: str = "active"
    elevation_m: Optional[float] = None
    district_id: Optional[UUID] = None
    village_id: Optional[UUID] = None
    metadata: Dict[str, Any] = {}
    installed_at: Optional[datetime] = None


class SensorStationRead(SensorStationBase, IDMixin, TimestampMixin):
    geom: Optional[PointGeometry] = None


class SensorParameterBase(BaseSchema):
    parameter_code: str
    parameter_name: str
    unit: str
    sensor_model: Optional[str] = None
    measurement_interval_minutes: int = 15
    min_value: Optional[float] = None
    max_value: Optional[float] = None


class SensorParameterRead(SensorParameterBase, IDMixin):
    station_id: UUID


class SensorReadingBase(BaseSchema):
    station_id: UUID
    parameter_id: UUID
    value: float
    quality_flag: str = "good"
    raw_value: Optional[float] = None
    metadata: Dict[str, Any] = {}


class SensorReadingCreate(SensorReadingBase):
    time: datetime


class SensorReadingRead(SensorReadingBase):
    time: datetime


# -----------------------------------------------------------------------------
# Hazard & Risk
# -----------------------------------------------------------------------------
class LandslideInventoryBase(BaseSchema):
    event_id: Optional[str] = None
    name: Optional[str] = None
    occurrence_date: datetime
    occurrence_time: Optional[datetime] = None
    trigger_type: Optional[str] = None
    landslide_type: Optional[str] = None
    volume_m3: Optional[float] = None
    area_m2: Optional[float] = None
    runout_distance_m: Optional[float] = None
    fatalities: int = 0
    injuries: int = 0
    houses_damaged: int = 0
    road_affected_m: Optional[float] = None
    district_id: Optional[UUID] = None
    block_id: Optional[UUID] = None
    village_id: Optional[UUID] = None
    data_source: Optional[str] = None
    confidence: str = "medium"
    metadata: Dict[str, Any] = {}


class LandslideInventoryRead(LandslideInventoryBase, IDMixin, TimestampMixin):
    geom: Optional[PolygonGeometry] = None
    centroid_geom: Optional[PointGeometry] = None


class SusceptibilityZoneBase(BaseSchema):
    zone_code: str
    name: Optional[str] = None
    susceptibility_class: str
    susceptibility_score: float
    model_version: str
    model_trained_at: datetime
    features_used: Dict[str, Any]
    district_id: Optional[UUID] = None
    area_km2: Optional[float] = None
    population_exposed: Optional[int] = None


class SusceptibilityZoneRead(SusceptibilityZoneBase, IDMixin, TimestampMixin):
    geom: Optional[MultiPolygonGeometry] = None


class RiskForecastBase(BaseSchema):
    zone_id: UUID
    forecast_timestamp: datetime
    valid_from: datetime
    valid_to: datetime
    risk_level: str
    risk_score: float
    triggering_factor: Optional[str] = None
    rainfall_forecast_mm: Optional[float] = None
    soil_moisture_pct: Optional[float] = None
    antecedent_rainfall_1d_mm: Optional[float] = None
    antecedent_rainfall_3d_mm: Optional[float] = None
    antecedent_rainfall_7d_mm: Optional[float] = None
    antecedent_rainfall_15d_mm: Optional[float] = None
    model_version: str
    shap_values: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = {}


class RiskForecastRead(RiskForecastBase, IDMixin):
    pass


# -----------------------------------------------------------------------------
# Alerts
# -----------------------------------------------------------------------------
class AlertRuleBase(BaseSchema):
    name: str
    description: Optional[str] = None
    severity: str
    trigger_condition: Dict[str, Any]
    target_audience: str
    channels: List[str]
    template_id: Optional[str] = None
    cooldown_minutes: int = 60
    is_active: bool = True
    priority: int = 100


class AlertRuleRead(AlertRuleBase, IDMixin, TimestampMixin):
    pass


class AlertBase(BaseSchema):
    rule_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    severity: str
    title: str
    message: str
    message_local: Optional[str] = None
    language: str = "en"
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = {}


class AlertRead(AlertBase, IDMixin):
    issued_at: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[UUID] = None
    status: str
    cap_identifier: Optional[str] = None
    cap_sent_at: Optional[datetime] = None


class AlertRecipientBase(BaseSchema):
    alert_id: UUID
    recipient_type: str
    recipient_id: str
    channel: str


class AlertRecipientRead(AlertRecipientBase, IDMixin):
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    status: str
    error_message: Optional[str] = None
    retry_count: int


# -----------------------------------------------------------------------------
# Citizen Reports
# -----------------------------------------------------------------------------
class CitizenReportBase(BaseSchema):
    reporter_name: Optional[str] = None
    reporter_phone: Optional[str] = None
    report_type: str
    severity: str = "unknown"
    description: Optional[str] = None
    accuracy_m: Optional[float] = None
    altitude_m: Optional[float] = None
    village_id: Optional[UUID] = None
    road_id: Optional[UUID] = None
    metadata: Dict[str, Any] = {}


class CitizenReportCreate(CitizenReportBase):
    geom: PointGeometry


class CitizenReportRead(CitizenReportBase, IDMixin, TimestampMixin):
    report_code: str
    geom: Optional[PointGeometry] = None
    status: str
    priority_score: float
    cv_classification: Optional[str] = None
    cv_confidence: Optional[float] = None
    cv_inference_at: Optional[datetime] = None
    verified_by: Optional[UUID] = None
    verified_at: Optional[datetime] = None
    verification_notes: Optional[str] = None
    assigned_to: Optional[UUID] = None
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None


class CitizenReportMediaBase(BaseSchema):
    media_type: str
    file_path: str
    file_size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_seconds: Optional[int] = None
    is_primary: bool = False


class CitizenReportMediaRead(CitizenReportMediaBase, IDMixin):
    report_id: UUID


# -----------------------------------------------------------------------------
# Users
# -----------------------------------------------------------------------------
class AppUserBase(BaseSchema):
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    state_id: Optional[UUID] = None
    district_id: Optional[UUID] = None
    block_id: Optional[UUID] = None
    village_id: Optional[UUID] = None
    preferred_language: str = "en"


class AppUserCreate(AppUserBase):
    password: str


class AppUserRead(AppUserBase, IDMixin, TimestampMixin):
    is_active: bool
    is_verified: bool
    last_login_at: Optional[datetime] = None


class AppUserUpdate(BaseSchema):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    preferred_language: Optional[str] = None
    role: Optional[str] = None
    state_id: Optional[UUID] = None
    district_id: Optional[UUID] = None
    block_id: Optional[UUID] = None
    village_id: Optional[UUID] = None


class Token(BaseSchema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# -----------------------------------------------------------------------------
# Pagination
# -----------------------------------------------------------------------------
class PageParams(BaseSchema):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


T = TypeVar("T")


class PaginatedResponse(BaseSchema, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int


# -----------------------------------------------------------------------------
# WebSocket messages
# -----------------------------------------------------------------------------
class WSMessage(BaseSchema):
    type: str
    payload: Dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# -----------------------------------------------------------------------------
# Health check
# -----------------------------------------------------------------------------
class HealthCheck(BaseSchema):
    status: str
    version: str
    environment: str
    checks: Dict[str, str]
