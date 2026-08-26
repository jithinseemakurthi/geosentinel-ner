"""
Set (or reset) an app_user password with a properly bcrypt-hashed value.

Usage:
    python scripts/set_admin_password.py --username admin
    DATABASE_URL=postgresql://... python scripts/set_admin_password.py --username admin

Requires: passlib[bcrypt], asyncpg (both already project dependencies).
"""
import argparse
import asyncio
import getpass
import os
import sys

MIN_PASSWORD_LENGTH = 8


async def set_password(database_url: str, username: str, password: str) -> bool:
    import asyncpg
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    password_hash = pwd_context.hash(password)

    conn = await asyncpg.connect(database_url)
    try:
        result = await conn.execute(
            """
            UPDATE app_user
            SET password_hash = $1,
                failed_login_attempts = 0,
                locked_until = NULL,
                updated_at = NOW()
            WHERE username = $2
            """,
            password_hash,
            username,
        )
        return result.strip() == "UPDATE 1"
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Set an app_user password (bcrypt).")
    parser.add_argument("--username", required=True, help="Username whose password to set")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        return 2

    password = getpass.getpass(f"New password for '{args.username}' (min {MIN_PASSWORD_LENGTH} chars): ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"ERROR: password must be at least {MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
        return 2
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("ERROR: passwords do not match.", file=sys.stderr)
        return 2

    ok = asyncio.run(set_password(database_url, args.username, password))
    if ok:
        print(f"Password updated for '{args.username}'.")
        return 0
    print(f"ERROR: user '{args.username}' not found.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
