"""Tests for geosentinel_shared.schemas."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from geosentinel_shared.schemas import (
    AlertRuleRead,
    PaginatedResponse,
    PointGeometry,
    RiskForecastRead,
    WSMessage,
)


class TestGeometry:
    def test_point_geometry_accepts_lon_lat(self):
        p = PointGeometry(type="Point", coordinates=[93.86, 24.81])
        assert p.coordinates[0] == 93.86  # lon first

    def test_point_geometry_rejects_polygon_type(self):
        with pytest.raises(ValidationError):
            PointGeometry(type="Polygon", coordinates=[[[0, 0], [1, 0], [1, 1], [0, 0]]])

    def test_shapely_roundtrip(self):
        from shapely.geometry import Point

        geom = Point(93.86, 24.81)
        wrapper = PointGeometry(type="Point", coordinates=[geom.x, geom.y])
        restored = wrapper.to_shapely()
        assert restored.equals(geom)


class TestWSMessage:
    def test_timestamp_defaults_to_utc_now(self):
        before = datetime.now(timezone.utc)
        msg = WSMessage(type="alert", payload={"a": 1})
        after = datetime.now(timezone.utc)
        # Regression: `timezone` was previously unimported (NameError).
        assert before.tzinfo is not None
        assert before <= msg.timestamp.replace(tzinfo=timezone.utc) <= after


class TestAlertSchemas:
    def test_alert_rule_requires_trigger_condition(self):
        base = dict(
            id=uuid4(),
            created_at=datetime.now(timezone.utc),
            name="r",
            severity="watch",
            target_audience="officials",
            channels=["sms"],
        )
        with pytest.raises(ValidationError):
            AlertRuleRead(**base)
        rule = AlertRuleRead(**base, trigger_condition={"risk_score": {">=": 0.8}})
        assert rule.trigger_condition["risk_score"][">="] == 0.8

    def test_risk_forecast_score_bounds_not_enforced_but_required(self):
        with pytest.raises(ValidationError):
            RiskForecastRead(id=uuid4())


class TestPagination:
    def test_page_params_bounds(self):
        from geosentinel_shared.schemas import PageParams

        assert PageParams().page == 1
        with pytest.raises(ValidationError):
            PageParams(page=0)
        with pytest.raises(ValidationError):
            PageParams(page_size=1000)

    def test_paginated_response_generic(self):
        resp = PaginatedResponse[PointGeometry](
            items=[PointGeometry(type="Point", coordinates=[0.0, 0.0])],
            total=1,
            page=1,
            page_size=20,
            total_pages=1,
        )
        assert resp.items[0].type == "Point"
