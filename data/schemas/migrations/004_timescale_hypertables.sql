-- =============================================================================
-- 004_timescale_hypertables.sql - TimescaleDB hypertables for sensor data
-- =============================================================================
-- Run ONLY on TimescaleDB instance

-- Enable TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- -----------------------------------------------------------------------------
-- Sensor readings hypertable (partitioned by time)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_reading (
    time TIMESTAMPTZ NOT NULL,
    station_id UUID NOT NULL,
    parameter_id UUID NOT NULL,
    value NUMERIC(12,4) NOT NULL,
    quality_flag VARCHAR(20) DEFAULT 'good',    -- good, suspect, bad, missing
    raw_value NUMERIC(12,4),                    -- Uncalibrated raw value
    metadata JSONB DEFAULT '{}',
    PRIMARY KEY (time, station_id, parameter_id)
);

SELECT create_hypertable('sensor_reading', 'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- Compression for older data
ALTER TABLE sensor_reading SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'station_id, parameter_id'
);

-- Compression policy: compress chunks older than 7 days
SELECT add_compression_policy('sensor_reading', INTERVAL '7 days', if_not_exists => TRUE);

-- Retention policy: drop raw readings older than 2 years (keep aggregates)
-- SELECT add_retention_policy('sensor_reading', INTERVAL '2 years', if_not_exists => TRUE);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_sensor_reading_station_time ON sensor_reading (station_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_sensor_reading_parameter_time ON sensor_reading (parameter_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_sensor_reading_station_param_time ON sensor_reading (station_id, parameter_id, time DESC);

-- -----------------------------------------------------------------------------
-- Continuous aggregates for common rollups
-- -----------------------------------------------------------------------------

-- Hourly aggregates
CREATE MATERIALIZED VIEW IF NOT EXISTS sensor_reading_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    station_id,
    parameter_id,
    COUNT(*) AS count,
    AVG(value) AS avg_value,
    MIN(value) AS min_value,
    MAX(value) AS max_value,
    STDDEV(value) AS stddev_value,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY value) AS median_value
FROM sensor_reading
GROUP BY bucket, station_id, parameter_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('sensor_reading_hourly',
    start_offset => INTERVAL '2 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

-- Daily aggregates
CREATE MATERIALIZED VIEW IF NOT EXISTS sensor_reading_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    station_id,
    parameter_id,
    COUNT(*) AS count,
    AVG(value) AS avg_value,
    MIN(value) AS min_value,
    MAX(value) AS max_value,
    SUM(value) AS sum_value,          -- Useful for rainfall accumulation
    STDDEV(value) AS stddev_value
FROM sensor_reading
GROUP BY bucket, station_id, parameter_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('sensor_reading_daily',
    start_offset => INTERVAL '2 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists => TRUE);

-- -----------------------------------------------------------------------------
-- Rainfall accumulation helper view (for antecedent rainfall calculation)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW rainfall_accumulation AS
SELECT
    sr.station_id,
    sr.time,
    -- 1-hour accumulation
    SUM(sr.value) OVER (
        PARTITION BY sr.station_id
        ORDER BY sr.time
        RANGE BETWEEN INTERVAL '1 hour' PRECEDING AND CURRENT ROW
    ) AS rainfall_1h_mm,
    -- 3-hour accumulation
    SUM(sr.value) OVER (
        PARTITION BY sr.station_id
        ORDER BY sr.time
        RANGE BETWEEN INTERVAL '3 hours' PRECEDING AND CURRENT ROW
    ) AS rainfall_3h_mm,
    -- 24-hour accumulation
    SUM(sr.value) OVER (
        PARTITION BY sr.station_id
        ORDER BY sr.time
        RANGE BETWEEN INTERVAL '24 hours' PRECEDING AND CURRENT ROW
    ) AS rainfall_24h_mm,
    -- 72-hour accumulation
    SUM(sr.value) OVER (
        PARTITION BY sr.station_id
        ORDER BY sr.time
        RANGE BETWEEN INTERVAL '72 hours' PRECEDING AND CURRENT ROW
    ) AS rainfall_72h_mm,
    -- 7-day accumulation
    SUM(sr.value) OVER (
        PARTITION BY sr.station_id
        ORDER BY sr.time
        RANGE BETWEEN INTERVAL '7 days' PRECEDING AND CURRENT ROW
    ) AS rainfall_7d_mm,
    -- 15-day accumulation
    SUM(sr.value) OVER (
        PARTITION BY sr.station_id
        ORDER BY sr.time
        RANGE BETWEEN INTERVAL '15 days' PRECEDING AND CURRENT ROW
    ) AS rainfall_15d_mm
FROM sensor_reading sr
JOIN sensor_parameter sp ON sr.parameter_id = sp.id
WHERE sp.parameter_code = 'rainfall'
  AND sr.quality_flag = 'good';

-- -----------------------------------------------------------------------------
-- Soil moisture anomaly detection (rolling statistics)
-- -----------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS soil_moisture_anomaly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', sr.time) AS bucket,
    sr.station_id,
    sr.parameter_id,
    AVG(sr.value) AS avg_moisture,
    AVG(sr.value) OVER (
        PARTITION BY sr.station_id, sr.parameter_id
        ORDER BY time_bucket('1 hour', sr.time)
        ROWS BETWEEN 167 AND 1    -- 7 days * 24 hours = 168 hours, exclude current
    ) AS rolling_7d_avg,
    STDDEV(sr.value) OVER (
        PARTITION BY sr.station_id, sr.parameter_id
        ORDER BY time_bucket('1 hour', sr.time)
        ROWS BETWEEN 167 AND 1
    ) AS rolling_7d_stddev,
    CASE
        WHEN STDDEV(sr.value) OVER (
            PARTITION BY sr.station_id, sr.parameter_id
            ORDER BY time_bucket('1 hour', sr.time)
            ROWS BETWEEN 167 AND 1
        ) > 0
        THEN (AVG(sr.value) - AVG(sr.value) OVER (
            PARTITION BY sr.station_id, sr.parameter_id
            ORDER BY time_bucket('1 hour', sr.time)
            ROWS BETWEEN 167 AND 1
        )) / STDDEV(sr.value) OVER (
            PARTITION BY sr.station_id, sr.parameter_id
            ORDER BY time_bucket('1 hour', sr.time)
            ROWS BETWEEN 167 AND 1
        )
        ELSE 0
    END AS z_score
FROM sensor_reading sr
JOIN sensor_parameter sp ON sr.parameter_id = sp.id
WHERE sp.parameter_code = 'soil_moisture'
  AND sr.quality_flag = 'good'
GROUP BY bucket, sr.station_id, sr.parameter_id
WITH NO DATA;

-- -----------------------------------------------------------------------------
-- InSAR displacement measurements (if separate table needed)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS insar_measurement (
    time TIMESTAMPTZ NOT NULL,
    point_id UUID NOT NULL,                       -- Persistent scatterer ID
    geometry GEOMETRY(POINT, 4326) NOT NULL,
    displacement_mm NUMERIC(8,3) NOT NULL,        -- Line-of-sight displacement
    velocity_mm_yr NUMERIC(8,3),                  -- Estimated velocity
    coherence NUMERIC(4,3),                       -- Interferometric coherence
    incidence_angle NUMERIC(5,2),
    track_number INT,
    satellite VARCHAR(50),                        -- S1A, S1B
    orbit_direction VARCHAR(20),                  -- ascending, descending
    quality_flag VARCHAR(20) DEFAULT 'good',
    metadata JSONB DEFAULT '{}',
    PRIMARY KEY (time, point_id)
);

SELECT create_hypertable('insar_measurement', 'time',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_insar_point_time ON insar_measurement (point_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_insar_geom ON insar_measurement USING GIST (geometry);

-- -----------------------------------------------------------------------------
-- Weather forecast cache (IMD API responses)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS weather_forecast (
    time TIMESTAMPTZ NOT NULL,                    -- Forecast timestamp
    district_id UUID NOT NULL,
    source VARCHAR(50) NOT NULL,                  -- IMD, ECMWF, GFS, etc.
    forecast_type VARCHAR(50),                    -- nowcast, short_range, medium_range
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NOT NULL,
    rainfall_mm NUMERIC(6,2),
    temperature_c NUMERIC(5,2),
    humidity_pct NUMERIC(5,2),
    wind_speed_kmh NUMERIC(6,2),
    wind_direction_deg INT,
    pressure_hpa NUMERIC(7,2),
    raw_response JSONB NOT NULL,                  -- Full API response
    PRIMARY KEY (time, district_id, source, forecast_type)
);

SELECT create_hypertable('weather_forecast', 'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_weather_forecast_district_valid ON weather_forecast (district_id, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_weather_forecast_source ON weather_forecast (source);

-- -----------------------------------------------------------------------------
-- Alert delivery tracking (high volume)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_delivery_log (
    time TIMESTAMPTZ NOT NULL,
    alert_id UUID NOT NULL,
    recipient_id UUID NOT NULL,
    channel VARCHAR(20) NOT NULL,
    provider VARCHAR(50),                         -- msg91, firebase, whatsapp, cap
    provider_message_id VARCHAR(200),
    status VARCHAR(20) NOT NULL,                  -- queued, sent, delivered, failed, read
    error_code VARCHAR(50),
    error_message TEXT,
    latency_ms INT,
    cost_paise INT,                               -- Cost in paise (1/100 INR)
    PRIMARY KEY (time, alert_id, recipient_id, channel)
);

SELECT create_hypertable('alert_delivery_log', 'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_alert_delivery_alert ON alert_delivery_log (alert_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_alert_delivery_recipient ON alert_delivery_log (recipient_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_alert_delivery_status ON alert_delivery_log (status, time DESC);