-- =============================================================================
-- 001_init_extensions.sql - Enable PostGIS and required extensions
-- =============================================================================
-- Run on both primary DB and TimescaleDB

-- PostGIS for spatial data
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
CREATE EXTENSION IF NOT EXISTS postgis_tiger_geocoder;

-- UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- TimescaleDB (only on timescaledb instance)
-- CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Additional useful extensions
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS hstore;
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Verify
SELECT PostGIS_Version();