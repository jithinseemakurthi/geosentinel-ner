-- =============================================================================
-- 002_create_tables.sql - Core application tables
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Administrative boundaries
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(10) UNIQUE NOT NULL,           -- e.g., 'ML', 'SK', 'MZ', 'AS', 'AR', 'MN', 'NL', 'TR'
    name_en VARCHAR(100) NOT NULL,
    name_local VARCHAR(100),
    geom GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_district (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state_id UUID NOT NULL REFERENCES admin_state(id),
    code VARCHAR(20) NOT NULL,                  -- e.g., 'EKH', 'EGH', 'WKH'
    name_en VARCHAR(100) NOT NULL,
    name_local VARCHAR(100),
    headquarters VARCHAR(100),
    population BIGINT,
    geom GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (state_id, code)
);

CREATE TABLE IF NOT EXISTS admin_block (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    district_id UUID NOT NULL REFERENCES admin_district(id),
    code VARCHAR(20) NOT NULL,
    name_en VARCHAR(100) NOT NULL,
    name_local VARCHAR(100),
    geom GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (district_id, code)
);

CREATE TABLE IF NOT EXISTS admin_village (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    block_id UUID NOT NULL REFERENCES admin_block(id),
    code VARCHAR(30) NOT NULL,                  -- Census code
    name_en VARCHAR(100) NOT NULL,
    name_local VARCHAR(100),
    population INT,
    households INT,
    geom GEOMETRY(POINT, 4326) NOT NULL,        -- Village centroid
    boundary_geom GEOMETRY(POLYGON, 4326),      -- Village boundary if available
    is_remote BOOLEAN DEFAULT FALSE,            -- Low connectivity flag
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (block_id, code)
);

-- -----------------------------------------------------------------------------
-- Infrastructure
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS infrastructure_road (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200),
    road_type VARCHAR(50),                      -- NH, SH, MDR, ODR, VR, Track
    surface_type VARCHAR(50),                   -- BT, CC, WBM, Earthen
    width_m NUMERIC(5,2),
    condition VARCHAR(20),                      -- Good, Fair, Poor, Blocked
    is_critical BOOLEAN DEFAULT FALSE,          -- Lifeline route
    geom GEOMETRY(LINESTRING, 4326) NOT NULL,
    district_id UUID REFERENCES admin_district(id),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS infrastructure_bridge (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200),
    road_id UUID REFERENCES infrastructure_road(id),
    bridge_type VARCHAR(50),
    span_m NUMERIC(6,2),
    condition VARCHAR(20),
    geom GEOMETRY(POINT, 4326) NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS infrastructure_facility (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    facility_type VARCHAR(50) NOT NULL,         -- Hospital, School, Police, Admin, Shelter, Helipad
    capacity INT,
    contact_phone VARCHAR(20),
    contact_email VARCHAR(100),
    is_operational BOOLEAN DEFAULT TRUE,
    geom GEOMETRY(POINT, 4326) NOT NULL,
    district_id UUID REFERENCES admin_district(id),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Sensor Network
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_station (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    station_code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(200),
    station_type VARCHAR(50) NOT NULL,          -- AWS, ARG, SoilMoisture, Tiltmeter, Piezometer, InSAR
    network VARCHAR(50),                        -- IMD, ISRO, State, Project
    status VARCHAR(20) DEFAULT 'active',        -- active, maintenance, decommissioned
    geom GEOMETRY(POINT, 4326) NOT NULL,
    elevation_m NUMERIC(8,2),
    district_id UUID REFERENCES admin_district(id),
    village_id UUID REFERENCES admin_village(id),
    metadata JSONB DEFAULT '{}',                -- Sensor specs, calibration, etc.
    installed_at DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sensor_parameter (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    station_id UUID NOT NULL REFERENCES sensor_station(id) ON DELETE CASCADE,
    parameter_code VARCHAR(50) NOT NULL,        -- rainfall, soil_moisture, tilt_x, tilt_y, pore_pressure, displacement
    parameter_name VARCHAR(100) NOT NULL,
    unit VARCHAR(20) NOT NULL,
    sensor_model VARCHAR(100),
    measurement_interval_minutes INT DEFAULT 15,
    min_value NUMERIC,
    max_value NUMERIC,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (station_id, parameter_code)
);

-- -----------------------------------------------------------------------------
-- Hazard & Risk
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS landslide_inventory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id VARCHAR(100),                      -- External ID (GSI, NIDM, local)
    name VARCHAR(200),
    occurrence_date DATE NOT NULL,
    occurrence_time TIME,
    trigger_type VARCHAR(50),                   -- Rainfall, Earthquake, Anthropogenic, Unknown
    landslide_type VARCHAR(50),                 -- Debris flow, Rock fall, Rotational slide, etc.
    volume_m3 NUMERIC(15,2),
    area_m2 NUMERIC(12,2),
    runout_distance_m NUMERIC(8,2),
    fatalities INT DEFAULT 0,
    injuries INT DEFAULT 0,
    houses_damaged INT DEFAULT 0,
    road_affected_m NUMERIC(10,2),
    geom GEOMETRY(POLYGON, 4326) NOT NULL,      -- Source area / deposit polygon
    centroid_geom GEOMETRY(POINT, 4326) GENERATED ALWAYS AS (ST_Centroid(geom)) STORED,
    district_id UUID REFERENCES admin_district(id),
    block_id UUID REFERENCES admin_block(id),
    village_id UUID REFERENCES admin_village(id),
    data_source VARCHAR(100),                   -- GSI Bhukosh, NIDM, Media, Field survey
    confidence VARCHAR(20) DEFAULT 'medium',    -- high, medium, low
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS susceptibility_zone (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    zone_code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(200),
    susceptibility_class VARCHAR(20) NOT NULL,  -- Very Low, Low, Moderate, High, Very High
    susceptibility_score NUMERIC(5,4) NOT NULL, -- 0.0 - 1.0
    model_version VARCHAR(50) NOT NULL,
    model_trained_at TIMESTAMPTZ NOT NULL,
    features_used JSONB NOT NULL,               -- Feature names and importance
    geom GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
    district_id UUID REFERENCES admin_district(id),
    area_km2 NUMERIC(10,2),
    population_exposed BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS risk_forecast (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    zone_id UUID NOT NULL REFERENCES susceptibility_zone(id),
    forecast_timestamp TIMESTAMPTZ NOT NULL,    -- When forecast was made
    valid_from TIMESTAMPTZ NOT NULL,            -- Forecast period start
    valid_to TIMESTAMPTZ NOT NULL,              -- Forecast period end
    risk_level VARCHAR(20) NOT NULL,            -- Watch, Warning, Evacuation
    risk_score NUMERIC(5,4) NOT NULL,           -- 0.0 - 1.0 probability
    triggering_factor VARCHAR(50),              -- rainfall, soil_moisture, combined
    rainfall_forecast_mm NUMERIC(6,2),
    soil_moisture_pct NUMERIC(5,2),
    antecedent_rainfall_1d_mm NUMERIC(6,2),
    antecedent_rainfall_3d_mm NUMERIC(6,2),
    antecedent_rainfall_7d_mm NUMERIC(6,2),
    antecedent_rainfall_15d_mm NUMERIC(6,2),
    model_version VARCHAR(50) NOT NULL,
    shap_values JSONB,                          -- Explainability
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (zone_id, forecast_timestamp, valid_from)
);

-- -----------------------------------------------------------------------------
-- Alerts & Notifications
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_rule (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    severity VARCHAR(20) NOT NULL,              -- watch, warning, evacuation
    trigger_condition JSONB NOT NULL,           -- e.g., {"risk_score": {">=": 0.8}, "duration_h": 3}
    target_audience VARCHAR(50) NOT NULL,       -- officials, community, all
    channels JSONB NOT NULL,                    -- ["sms", "push", "whatsapp", "cap"]
    template_id VARCHAR(100),
    cooldown_minutes INT DEFAULT 60,
    is_active BOOLEAN DEFAULT TRUE,
    priority INT DEFAULT 100,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alert (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id UUID REFERENCES alert_rule(id),
    zone_id UUID REFERENCES susceptibility_zone(id),
    severity VARCHAR(20) NOT NULL,              -- watch, warning, evacuation
    title VARCHAR(500) NOT NULL,
    message TEXT NOT NULL,
    message_local TEXT,                         -- Translated message
    language VARCHAR(10) DEFAULT 'en',
    issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by UUID,                       -- User ID
    status VARCHAR(20) DEFAULT 'active',        -- active, acknowledged, expired, cancelled
    cap_identifier VARCHAR(200),                -- CAP message ID
    cap_sent_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alert_recipient (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id UUID NOT NULL REFERENCES alert(id) ON DELETE CASCADE,
    recipient_type VARCHAR(20) NOT NULL,        -- user, village, district, role
    recipient_id VARCHAR(100) NOT NULL,         -- User ID, village code, district code, role name
    channel VARCHAR(20) NOT NULL,               -- sms, push, whatsapp, email, cap, siren
    sent_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    read_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'pending',       -- pending, sent, delivered, failed, read
    error_message TEXT,
    retry_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (alert_id, recipient_id, channel)
);

-- -----------------------------------------------------------------------------
-- Citizen Reports
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS citizen_report (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_code VARCHAR(20) UNIQUE NOT NULL,    -- Human-readable: GSN-2024-001234
    reporter_id UUID,                           -- Nullable for anonymous
    reporter_name VARCHAR(200),
    reporter_phone VARCHAR(20),
    report_type VARCHAR(50) NOT NULL,           -- crack, bulge, subsidence, debris, rockfall, road_block, water_spring, other
    severity VARCHAR(20) DEFAULT 'unknown',     -- low, medium, high, critical, unknown
    description TEXT,
    geom GEOMETRY(POINT, 4326) NOT NULL,
    accuracy_m NUMERIC(6,2),                    -- GPS accuracy
    altitude_m NUMERIC(8,2),
    village_id UUID REFERENCES admin_village(id),
    road_id UUID REFERENCES infrastructure_road(id),
    status VARCHAR(20) DEFAULT 'submitted',     -- submitted, triaged, verified, rejected, escalated, resolved
    priority_score NUMERIC(5,2) DEFAULT 0,      -- Computed priority for response
    cv_classification VARCHAR(50),              -- From M3 model
    cv_confidence NUMERIC(4,3),
    cv_inference_at TIMESTAMPTZ,
    verified_by UUID,
    verified_at TIMESTAMPTZ,
    verification_notes TEXT,
    assigned_to UUID,                           -- Field officer
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS citizen_report_media (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID NOT NULL REFERENCES citizen_report(id) ON DELETE CASCADE,
    media_type VARCHAR(20) NOT NULL,            -- photo, video, audio
    file_path VARCHAR(500) NOT NULL,            -- MinIO object path
    file_size_bytes BIGINT,
    mime_type VARCHAR(100),
    width INT,
    height INT,
    duration_seconds INT,                       -- For video/audio
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Users & Authentication
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_user (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(20) UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(200),
    role VARCHAR(50) NOT NULL,                  -- admin, state_officer, district_officer, block_officer, field_officer, citizen, volunteer
    state_id UUID REFERENCES admin_state(id),
    district_id UUID REFERENCES admin_district(id),
    block_id UUID REFERENCES admin_block(id),
    village_id UUID REFERENCES admin_village(id),
    preferred_language VARCHAR(10) DEFAULT 'en',
    is_active BOOLEAN DEFAULT TRUE,
    is_verified BOOLEAN DEFAULT FALSE,
    last_login_at TIMESTAMPTZ,
    failed_login_attempts INT DEFAULT 0,
    locked_until TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_device (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    device_token VARCHAR(500) NOT NULL,         -- FCM/APNs token
    platform VARCHAR(20) NOT NULL,              -- android, ios, web
    app_version VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, device_token)
);

-- -----------------------------------------------------------------------------
-- Audit & Sync
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL,
    record_id UUID NOT NULL,
    action VARCHAR(20) NOT NULL,                -- INSERT, UPDATE, DELETE
    old_data JSONB,
    new_data JSONB,
    user_id UUID REFERENCES app_user(id),
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sync_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(50) NOT NULL,           -- citizen_report, sensor_reading, etc.
    entity_id UUID NOT NULL,
    operation VARCHAR(20) NOT NULL,             -- create, update, delete
    payload JSONB NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',       -- pending, synced, failed, conflict
    attempts INT DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    synced_at TIMESTAMPTZ
);

-- -----------------------------------------------------------------------------
-- Triggers for updated_at
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_admin_state_updated_at BEFORE UPDATE ON admin_state FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_admin_district_updated_at BEFORE UPDATE ON admin_district FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_admin_block_updated_at BEFORE UPDATE ON admin_block FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_admin_village_updated_at BEFORE UPDATE ON admin_village FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_infrastructure_road_updated_at BEFORE UPDATE ON infrastructure_road FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_infrastructure_bridge_updated_at BEFORE UPDATE ON infrastructure_bridge FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_infrastructure_facility_updated_at BEFORE UPDATE ON infrastructure_facility FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_sensor_station_updated_at BEFORE UPDATE ON sensor_station FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_alert_rule_updated_at BEFORE UPDATE ON alert_rule FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_citizen_report_updated_at BEFORE UPDATE ON citizen_report FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_app_user_updated_at BEFORE UPDATE ON app_user FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();