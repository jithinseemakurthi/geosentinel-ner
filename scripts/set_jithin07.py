"""
Create or update the Jithin07 account (username=Jithin07, password=123456789).

Usage:
    # ensure Docker stack is up so Postgres is reachable
    docker compose up -d postgres

    # then run (uses DATABASE_URL from .env):
    python scripts/set_jithin07.py
    # or: DATABASE_URL=postgresql://... python scripts/set_jithin07.py

Requires: asyncpg, passlib[bcrypt] (already in requirements-dev.txt / geosentinel_shared).
"""
import asyncio
import os
import sys

USERNAME = "Jithin07"
PASSWORD = "123456789"
EMAIL = "jithin07@geosentinel.local"
FULL_NAME = "Jithin"
ROLE = "admin"  # gives full dashboard access; change to district_officer if needed


async def main() -> int:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        # fallback to .env default
        try:
            from dotenv import load_dotenv  # type: ignore
            load_dotenv()
            db_url = os.environ.get("DATABASE_URL", "")
        except Exception:
            pass
    if not db_url:
        db_url = "postgresql://geosentinel:UQQMEKNC83gbXHBU9k9Zv05RkQj285e0@localhost:5432/geosentinel"
        print(f"DATABASE_URL not set — trying default {db_url}", file=sys.stderr)

    try:
        import asyncpg
        from passlib.context import CryptContext
    except ImportError as e:
        print(f"Missing dependency: {e}. Run: pip install asyncpg passlib[bcrypt]", file=sys.stderr)
        return 2

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    password_hash = pwd_context.hash(PASSWORD)

    print(f"Connecting to {db_url.split('@')[-1]} ...")
    try:
        conn = await asyncpg.connect(db_url)
    except Exception as e:
        print(f"DB connect failed: {e}", file=sys.stderr)
        print("Is Docker running? Try: docker compose up -d postgres", file=sys.stderr)
        return 2

    try:
        # Create or update Jithin07 — keeps account unlocked and active
        await conn.execute(
            """
            INSERT INTO app_user (username, email, password_hash, full_name, role,
                                  is_active, is_verified, preferred_language,
                                  failed_login_attempts, locked_until)
            VALUES ($1, $2, $3, $4, $5, TRUE, TRUE, 'en', 0, NULL)
            ON CONFLICT (username) DO UPDATE
            SET password_hash = EXCLUDED.password_hash,
                email = EXCLUDED.email,
                full_name = EXCLUDED.full_name,
                role = EXCLUDED.role,
                is_active = TRUE,
                is_verified = TRUE,
                failed_login_attempts = 0,
                locked_until = NULL,
                updated_at = NOW()
            """,
            USERNAME,
            EMAIL,
            password_hash,
            FULL_NAME,
            ROLE,
        )
        row = await conn.fetchrow("SELECT username, email, role, is_active FROM app_user WHERE username=$1", USERNAME)
        print(f"Done — user ready: {dict(row) if row else USERNAME}")
        print(f"  username: {USERNAME}")
        print(f"  password: {PASSWORD}")
        print(f"  role:     {ROLE}")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
