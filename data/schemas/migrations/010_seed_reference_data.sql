-- =============================================================================
-- 010_seed_reference_data.sql - Reference data for NER states, languages, etc.
-- =============================================================================
-- IMPORTANT: this migration only seeds reference data that has NO geometry.
-- Real state/district/block/village geometry is loaded separately from the
-- official Survey of India / Bhuvan shapefiles using ogr2ogr or pgsql2shp
-- scripts in data/samples/load_boundaries.sh.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Default alert rules (5 starter rules; officials can customise per state)
-- -----------------------------------------------------------------------------
INSERT INTO alert_rule (name, description, severity, trigger_condition, target_audience, channels, template_id, cooldown_minutes, priority) VALUES
(
    'High Risk - Imminent Rainfall',
    'Triggered when dynamic risk score exceeds 0.8 for any zone with heavy rainfall forecast',
    'warning',
    '{"risk_score": {">=": 0.8}, "rainfall_forecast_mm": {">=": 100}, "valid_duration_h": {">=": 6}}',
    'all',
    '["sms", "push", "whatsapp", "cap"]',
    'alert_high_risk_rainfall',
    120,
    10
),
(
    'Critical Risk - Evacuation Advised',
    'Triggered when risk score exceeds 0.95 with confirmed sensor anomalies',
    'evacuation',
    '{"risk_score": {">=": 0.95}, "sensor_anomaly_confirmed": true}',
    'community',
    '["sms", "push", "whatsapp", "cap", "siren"]',
    'alert_evacuation',
    0,
    1
),
(
    'Watch - Elevated Risk',
    'Early watch when risk score exceeds 0.6 for 12+ hours',
    'watch',
    '{"risk_score": {">=": 0.6}, "valid_duration_h": {">=": 12}}',
    'officials',
    '["email", "push"]',
    'alert_watch_elevated',
    360,
    50
),
(
    'Road Blockage Reported',
    'Citizen report of road blockage on critical route',
    'warning',
    '{"report_type": "road_block", "road_is_critical": true, "verification": "verified"}',
    'all',
    '["sms", "push", "whatsapp"]',
    'alert_road_blockage',
    60,
    20
),
(
    'Slope Movement Detected',
    'Citizen report or sensor detection of active slope movement',
    'warning',
    '{"OR": [{"report_type": {"IN": ["crack", "bulge", "subsidence"]}, "cv_confidence": {">=": 0.7}}, {"sensor_tilt_threshold_exceeded": true}]}',
    'officials',
    '["email", "push", "sms"]',
    'alert_slope_movement',
    30,
    15
)
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- Seed an initial admin user for first-time setup.
--
-- IMPORTANT: the password_hash below is intentionally INVALID (a placeholder).
-- Login is disabled for this account until you set a real bcrypt hash:
--
--   make set-admin-password            # prompts securely for a new password
--   # or directly:
--   python scripts/set_admin_password.py --username admin
--
-- Never ship a deployment with a default/known admin password.
-- -----------------------------------------------------------------------------
INSERT INTO app_user (
    username, email, password_hash, full_name, role, is_active, is_verified, preferred_language
) VALUES (
    'admin',
    'admin@geosentinel.example.gov.in',
    -- placeholder, not a valid bcrypt digest — replaced via
    -- scripts/set_admin_password.py before first login
    '$2b$12$PLACEHOLDERREPLACEMEVIAsetadminpasswordscript000000000000000000',
    'System Administrator',
    'admin',
    TRUE,
    TRUE,
    'en'
)
ON CONFLICT (username) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Reference docs (kept as SQL comments, since they document the UI choices):
--   - Severity colors: very_low=#1a9850, low=#91cf60, moderate=#ffffbf,
--     high=#fc8d59, very_high=#d73027, watch=#fee08b, warning=#fc8d59,
--     evacuation=#d73027
--   - Report types: crack, bulge, subsidence, debris, rockfall, road_block,
--     water_spring, other
--   - Sensor types: AWS, ARG, SoilMoisture, Tiltmeter, Piezometer, InSAR, GNSS
-- -----------------------------------------------------------------------------
