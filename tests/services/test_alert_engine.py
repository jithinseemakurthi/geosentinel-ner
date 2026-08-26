"""Tests for the alert-engine rule evaluator and dispatcher helpers."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from conftest import load_service_module

alert_engine = load_service_module("alert_engine", "services/alert-engine/app/main.py")
RuleEvaluator = alert_engine.RuleEvaluator
AlertDispatcher = alert_engine.AlertDispatcher


class TestEvaluateCondition:
    CTX = {
        "risk_score": 0.85,
        "rainfall_forecast_mm": 120.0,
        "risk_level": "warning",
        "report_type": "crack",
        "sensor_anomaly_confirmed": True,
    }

    def test_equality_literal(self):
        assert RuleEvaluator.evaluate_condition({"risk_level": "warning"}, self.CTX)

    def test_numeric_operators(self):
        assert RuleEvaluator.evaluate_condition({"risk_score": {">=": 0.8}}, self.CTX)
        assert RuleEvaluator.evaluate_condition({"risk_score": {"<": 0.9}}, self.CTX)
        assert not RuleEvaluator.evaluate_condition({"risk_score": {">=": 0.95}}, self.CTX)

    def test_multiple_operator_entries_are_anded(self):
        cond = {"rainfall_forecast_mm": {">=": 100, "<": 200}}
        assert RuleEvaluator.evaluate_condition(cond, self.CTX)
        assert not RuleEvaluator.evaluate_condition({"rainfall_forecast_mm": {">=": 100, "<": 110}}, self.CTX)

    def test_in_and_not_in(self):
        cond = {"report_type": {"IN": ["crack", "bulge", "subsidence"]}}
        assert RuleEvaluator.evaluate_condition(cond, self.CTX)
        assert not RuleEvaluator.evaluate_condition(
            {"report_type": {"NOT_IN": ["crack"]}}, self.CTX
        )
        assert not RuleEvaluator.evaluate_condition({"report_type": {"in": ["debris"]}}, self.CTX)

    def test_contains(self):
        assert RuleEvaluator.evaluate_condition({"risk_level": {"contains": "arn"}}, self.CTX)
        assert not RuleEvaluator.evaluate_condition({"risk_level": {"contains": "evac"}}, self.CTX)

    def test_inequality(self):
        assert RuleEvaluator.evaluate_condition({"report_type": {"!=": "road_block"}}, self.CTX)

    def test_boolean_field(self):
        assert RuleEvaluator.evaluate_condition({"sensor_anomaly_confirmed": True}, self.CTX)
        assert not RuleEvaluator.evaluate_condition({"sensor_anomaly_confirmed": False}, self.CTX)

    def test_top_level_keys_are_anded(self):
        seed_style = {"risk_score": {">=": 0.8}, "rainfall_forecast_mm": {">=": 100}}
        assert RuleEvaluator.evaluate_condition(seed_style, self.CTX)
        failing = dict(seed_style, risk_score={">=": 0.99})
        assert not RuleEvaluator.evaluate_condition(failing, self.CTX)

    def test_or_branches(self):
        cond = {
            "OR": [
                {"risk_score": {">=": 0.99}},
                {"rainfall_forecast_mm": {">=": 100}},
            ]
        }
        assert RuleEvaluator.evaluate_condition(cond, self.CTX)
        all_false = {"OR": [{"risk_score": {">=": 0.99}}, {"risk_level": "evacuation"}]}
        assert not RuleEvaluator.evaluate_condition(all_false, self.CTX)

    def test_not_negation(self):
        assert RuleEvaluator.evaluate_condition({"NOT": {"risk_level": "evacuation"}}, self.CTX)
        assert not RuleEvaluator.evaluate_condition({"NOT": {"risk_level": "warning"}}, self.CTX)

    def test_nested_combinators(self):
        # Mirrors the seeded 'Slope Movement Detected' rule.
        cond = {
            "OR": [
                {
                    "report_type": {"IN": ["crack", "bulge", "subsidence"]},
                    "cv_confidence": {">=": 0.7},
                },
                {"sensor_tilt_threshold_exceeded": True},
            ]
        }
        ctx = dict(self.CTX, cv_confidence=0.82)
        assert RuleEvaluator.evaluate_condition(cond, ctx)
        low_conf = dict(ctx, cv_confidence=0.4)
        assert not RuleEvaluator.evaluate_condition(cond, low_conf)
        sensor_hit = dict(low_conf, sensor_tilt_threshold_exceeded=True)
        assert RuleEvaluator.evaluate_condition(cond, sensor_hit)

    def test_missing_or_none_context_never_matches(self):
        cond = {"unknown_field": {">=": 1}}
        assert not RuleEvaluator.evaluate_condition(cond, self.CTX)
        none_ctx = {"rainfall_forecast_mm": None}
        assert not RuleEvaluator.evaluate_condition({"rainfall_forecast_mm": {"!=": 999}}, none_ctx)

    def test_non_dict_condition_is_false(self):
        assert not RuleEvaluator.evaluate_condition("risk_score >= 0.8", self.CTX)
        assert not RuleEvaluator.evaluate_condition(None, self.CTX)

    def test_unknown_operator_raises(self):
        with pytest.raises(ValueError, match="Unsupported rule operator"):
            RuleEvaluator.evaluate_condition({"risk_score": {"~>": 1}}, self.CTX)


class TestSeedRulesMatchRealConditions:
    """The five rules inserted by 010_seed_reference_data.sql must evaluate."""

    def test_high_risk_imminent_rainfire_rule(self):
        condition = {
            "risk_score": {">=": 0.8},
            "rainfall_forecast_mm": {">=": 100},
            "valid_duration_h": {">=": 6},
        }
        hit = {"risk_score": 0.81, "rainfall_forecast_mm": 102, "valid_duration_h": 6}
        miss = dict(hit, rainfall_forecast_mm=90)
        assert RuleEvaluator.evaluate_condition(condition, hit)
        assert not RuleEvaluator.evaluate_condition(condition, miss)


class FakeRow:
    """Mapping-style row mimicking SQLAlchemy RowMapping."""

    def __init__(self, data):
        self._data = dict(data)

    def __getitem__(self, key):
        return self._data[key]


def _forecast_row(**overrides):
    row = {
        "zone_id": uuid4(),
        "risk_level": "warning",
        "risk_score": 0.85,
        "rainfall_forecast_mm": 110,
        "soil_moisture_pct": 41.5,
        "antecedent_rainfall_1d_mm": 20,
        "antecedent_rainfall_3d_mm": 55,
        "antecedent_rainfall_7d_mm": 80,
        "valid_from": datetime.now(timezone.utc),
        "valid_to": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    return FakeRow({**row, **overrides})


class TestHelpers:
    def test_as_mapping_parses_json_strings(self):
        assert RuleEvaluator._as_mapping('{"a": 1}') == {"a": 1}
        assert RuleEvaluator._as_mapping({"a": 1}) == {"a": 1}
        assert RuleEvaluator._as_mapping("not json") == {}
        assert RuleEvaluator._as_mapping(b"[1]") == {}

    def test_as_list_parses_channels(self):
        assert AlertDispatcher._as_list('["sms","push"]') == ["sms", "push"]
        assert AlertDispatcher._as_list(["sms"]) == ["sms"]
        assert AlertDispatcher._as_list(None) == []

    def test_forecast_context_values(self):
        fc = _forecast_row()
        ctx = RuleEvaluator._forecast_context(fc)
        assert ctx["risk_score"] == 0.85
        assert ctx["valid_duration_h"] == pytest.approx(12.0)
        assert ctx["rainfall_forecast_mm"] == 110.0


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def one(self):
        return self._rows[0]


class FakeSession:
    """Minimal AsyncSession stand-in covering the evaluator's SQL surface."""

    def __init__(self, rules=(), forecasts=(), cooldown_free=True):
        self.rules = list(rules)
        self.forecasts = list(forecasts)
        self.cooldown_free = cooldown_free
        self.inserted_alerts = []
        self.executed = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append(sql)
        if "FROM alert_rule" in sql:
            return FakeResult(self.rules)
        if "FROM risk_forecast" in sql:
            return FakeResult(self.forecasts)
        if "INSERT INTO alert" in sql:
            self.inserted_alerts.append(params)
            return FakeResult([{"id": params["id"], "issued_at": datetime.now(timezone.utc)}])
        if "LIMIT 1" in sql:
            return FakeResult([] if self.cooldown_free else [{"active": 1}])
        raise AssertionError(f"Unexpected SQL in test: {sql[:60]}")


def _rule_row(**overrides):
    rule = {
        "id": uuid4(),
        "name": "High Risk - Imminent Rainfall",
        "severity": "warning",
        "trigger_condition": '{"risk_score": {">=": 0.8}, "rainfall_forecast_mm": {">=": 100}}',
        "target_audience": "all",
        "channels": '["sms", "push"]',
        "template_id": "alert_high_risk_rainfall",
        "cooldown_minutes": 120,
    }
    return FakeRow({**rule, **overrides})


class TestEvaluateAllRules:
    async def test_trigger_creates_persisted_alert(self):
        session = FakeSession(rules=[_rule_row()], forecasts=[_forecast_row()])
        triggered = await RuleEvaluator(session).evaluate_all_rules()
        assert len(triggered) == 1
        assert len(session.inserted_alerts) == 1
        saved = session.inserted_alerts[0]
        assert saved["severity"] == "warning"
        assert '"trigger_context"' in saved["metadata"]

    async def test_cooldown_suppresses_duplicate_alert(self):
        session = FakeSession(rules=[_rule_row()], forecasts=[_forecast_row()], cooldown_free=False)
        assert await RuleEvaluator(session).evaluate_all_rules() == []
        assert session.inserted_alerts == []

    async def test_no_forecast_means_no_alert(self):
        session = FakeSession(rules=[_rule_row()], forecasts=[])
        assert await RuleEvaluator(session).evaluate_all_rules() == []

    async def test_invalid_condition_skipped_without_crash(self):
        broken = _rule_row(trigger_condition="not-json{")
        session = FakeSession(rules=[broken], forecasts=[_forecast_row()])
        assert await RuleEvaluator(session).evaluate_all_rules() == []
