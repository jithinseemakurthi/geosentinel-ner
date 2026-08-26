"""
GeoSentinel-NER Shared Authentication Module
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from . import config

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"
JWT_ISSUER = "geosentinel-ner"
JWT_AUDIENCE = "geosentinel-api"


class TokenPayload(BaseModel):
    sub: UUID
    username: str
    role: str
    exp: int
    iat: int
    type: str  # "access" or "refresh"
    iss: str
    aud: str
    jti: Optional[str] = None  # unique token id — used for revocation denylists


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    subject: UUID,
    username: str,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Issue a short-lived access token. Server-side RBAC is the source of
    truth for permissions — never trust permissions from the token itself."""
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=config.settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub": str(subject),
        "username": username,
        "role": role,
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "type": "access",
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "jti": uuid4().hex,
    }
    return jwt.encode(payload, config.settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(subject: UUID, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=config.settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(subject),
        "username": username,
        "role": role,
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "type": "refresh",
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "jti": uuid4().hex,
    }
    return jwt.encode(payload, config.settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(
            token,
            config.settings.SECRET_KEY,
            algorithms=[ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
        )
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}")
    return TokenPayload(**payload)


def verify_token(token: str, token_type: str = "access") -> TokenPayload:
    payload = decode_token(token)
    if payload.type != token_type:
        raise ValueError(f"Invalid token type: expected {token_type}, got {payload.type}")
    if payload.exp < datetime.now(timezone.utc).timestamp():
        raise ValueError("Token has expired")
    return payload


# Role-based permissions (server-side source of truth — DB-backed in production)
ROLE_PERMISSIONS = {
    "admin": {"all": True},
    "state_officer": {
        "states": ["read", "write"],
        "districts": ["read", "write"],
        "alerts": ["read", "write", "acknowledge"],
        "reports": ["read", "verify", "assign"],
        "users": ["read", "write"],
        "settings": ["read", "write"],
    },
    "district_officer": {
        "districts": ["read", "write"],
        "blocks": ["read", "write"],
        "villages": ["read", "write"],
        "alerts": ["read", "write", "acknowledge", "issue"],
        "reports": ["read", "verify", "assign", "resolve"],
        "roads": ["read", "write"],
        "facilities": ["read", "write"],
        "sensors": ["read"],
    },
    "block_officer": {
        "blocks": ["read", "write"],
        "villages": ["read", "write"],
        "alerts": ["read", "acknowledge"],
        "reports": ["read", "verify", "assign", "resolve"],
        "roads": ["read"],
        "facilities": ["read"],
    },
    "field_officer": {
        "villages": ["read"],
        "reports": ["read", "create", "update_own"],
        "alerts": ["read"],
        "sensor_data": ["read"],
    },
    "citizen": {
        "reports": ["create", "read_own"],
        "alerts": ["read"],
        "profile": ["read", "write"],
    },
    "volunteer": {
        "reports": ["create", "read", "verify"],
        "alerts": ["read"],
        "villages": ["read"],
    },
}


def check_permission(role: str, resource: str, action: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role, {})
    if perms.get("all"):
        return True
    resource_perms = perms.get(resource, [])
    return action in resource_perms or "all" in resource_perms
