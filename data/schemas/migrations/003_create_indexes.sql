-- =============================================================================
-- 003_create_indexes.sql - Spatial and performance indexes
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Spatial indexes (GiST)
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_admin_state_geom ON admin_state USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_admin_district_geom ON admin_district USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_admin_block_geom ON admin_block USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_admin_village_geom ON admin_village USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_admin_village_boundary_geom ON admin_village USING GIST (boundary_geom);

CREATE INDEX IF NOT EXISTS idx_infrastructure_road_geom ON infrastructure_road USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_infrastructure_bridge_geom ON infrastructure_bridge USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_infrastructure_facility_geom ON infrastructure_facility USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_sensor_station_geom ON sensor_station USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_landslide_inventory_geom ON landslide_inventory USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_landslide_inventory_centroid ON landslide_inventory USING GIST (centroid_geom);

CREATE INDEX IF NOT EXISTS idx_susceptibility_zone_geom ON susceptibility_zone USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_citizen_report_geom ON citizen_report USING GIST (geom);

-- -----------------------------------------------------------------------------
-- Temporal indexes
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_landslide_inventory_date ON landslide_inventory (occurrence_date DESC);
CREATE INDEX IF NOT EXISTS idx_risk_forecast_valid_period ON risk_forecast (valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_risk_forecast_timestamp ON risk_forecast (forecast_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_alert_issued_at ON alert (issued_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_expires_at ON alert (expires_at);
CREATE INDEX IF NOT EXISTS idx_citizen_report_created_at ON citizen_report (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_queue_created_at ON sync_queue (created_at DESC);

-- -----------------------------------------------------------------------------
-- Foreign key / lookup indexes
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_admin_district_state_id ON admin_district (state_id);
CREATE INDEX IF NOT EXISTS idx_admin_block_district_id ON admin_block (district_id);
CREATE INDEX IF NOT EXISTS idx_admin_village_block_id ON admin_village (block_id);

CREATE INDEX IF NOT EXISTS idx_infrastructure_road_district_id ON infrastructure_road (district_id);
CREATE INDEX IF NOT EXISTS idx_infrastructure_facility_district_id ON infrastructure_facility (district_id);

CREATE INDEX IF NOT EXISTS idx_sensor_station_district_id ON sensor_station (district_id);
CREATE INDEX IF NOT EXISTS idx_sensor_parameter_station_id ON sensor_parameter (station_id);

CREATE INDEX IF NOT EXISTS idx_landslide_inventory_district_id ON landslide_inventory (district_id);
CREATE INDEX IF NOT EXISTS idx_landslide_inventory_block_id ON landslide_inventory (block_id);
CREATE INDEX IF NOT EXISTS idx_landslide_inventory_village_id ON landslide_inventory (village_id);

CREATE INDEX IF NOT EXISTS idx_susceptibility_zone_district_id ON susceptibility_zone (district_id);

CREATE INDEX IF NOT EXISTS idx_risk_forecast_zone_id ON risk_forecast (zone_id);
CREATE INDEX IF NOT EXISTS idx_alert_zone_id ON alert (zone_id);
CREATE INDEX IF NOT EXISTS idx_alert_rule_id ON alert (rule_id);

CREATE INDEX IF NOT EXISTS idx_citizen_report_village_id ON citizen_report (village_id);
CREATE INDEX IF NOT EXISTS idx_citizen_report_road_id ON citizen_report (road_id);
CREATE INDEX IF NOT EXISTS idx_citizen_report_status ON citizen_report (status);
CREATE INDEX IF NOT EXISTS idx_citizen_report_reporter_id ON citizen_report (reporter_id);

CREATE INDEX IF NOT EXISTS idx_citizen_report_media_report_id ON citizen_report_media (report_id);

CREATE INDEX IF NOT EXISTS idx_app_user_district_id ON app_user (district_id);
CREATE INDEX IF NOT EXISTS idx_app_user_block_id ON app_user (block_id);
CREATE INDEX IF NOT EXISTS idx_app_user_village_id ON app_user (village_id);
CREATE INDEX IF NOT EXISTS idx_app_user_role ON app_user (role);

CREATE INDEX IF NOT EXISTS idx_user_device_user_id ON user_device (user_id);

CREATE INDEX IF NOT EXISTS idx_alert_recipient_alert_id ON alert_recipient (alert_id);
CREATE INDEX IF NOT EXISTS idx_alert_recipient_recipient ON alert_recipient (recipient_type, recipient_id);
CREATE INDEX IF NOT EXISTS idx_alert_recipient_status ON alert_recipient (status);

CREATE INDEX IF NOT EXISTS idx_audit_log_table_record ON audit_log (table_name, record_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log (user_id);

CREATE INDEX IF NOT EXISTS idx_sync_queue_entity ON sync_queue (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_sync_queue_status ON sync_queue (status);

-- -----------------------------------------------------------------------------
-- Partial / conditional indexes
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_alert_active ON alert (issued_at DESC) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_citizen_report_pending ON citizen_report (created_at DESC) WHERE status IN ('submitted', 'triaged');
CREATE INDEX IF NOT EXISTS idx_sensor_station_active ON sensor_station (station_type) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_infrastructure_road_blocked ON infrastructure_road (district_id) WHERE condition = 'Blocked';

-- -----------------------------------------------------------------------------
-- Composite indexes for common query patterns
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_risk_forecast_zone_time ON risk_forecast (zone_id, forecast_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_alert_zone_severity_time ON alert (zone_id, severity, issued_at DESC);
CREATE INDEX IF NOT EXISTS idx_citizen_report_village_status_time ON citizen_report (village_id, status, created_at DESC);