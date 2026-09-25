-- Create / update Jithin07 account (password = 123456789)
-- Run when Postgres is up:  docker compose up -d postgres
-- Then:  psql postgresql://geosentinel:UQQMEKNC83gbXHBU9k9Zv05RkQj285e0@localhost:5432/geosentinel -f insert_jithin07.sql
-- Or inside container:  docker compose exec postgres psql -U geosentinel -d geosentinel -f /path/to/insert_jithin07.sql

INSERT INTO app_user (username, email, password_hash, full_name, role, is_active, is_verified, preferred_language, failed_login_attempts, locked_until)
VALUES (
  'Jithin07',
  'jithin07@geosentinel.local',
  '$2b$12$MfAtv1Qz7fhs1swKfaCku.9HCmSUR4GQGRB0moCVgCKA2Q0eERRQm',
  'Jithin',
  'admin',
  TRUE, TRUE, 'en', 0, NULL
)
ON CONFLICT (username) DO UPDATE
SET password_hash = EXCLUDED.password_hash,
    email = EXCLUDED.email,
    full_name = EXCLUDED.full_name,
    role = EXCLUDED.role,
    is_active = TRUE,
    is_verified = TRUE,
    failed_login_attempts = 0,
    locked_until = NULL,
    updated_at = NOW();

-- verify
SELECT username, email, role, is_active FROM app_user WHERE username='Jithin07';
