"""Tests for geosentinel_shared.auth (JWT, passwords, RBAC)."""
from datetime import timedelta
from uuid import uuid4

import pytest

from geosentinel_shared.auth import (
    ROLE_PERMISSIONS,
    check_permission,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
    verify_token,
)


class TestPasswords:
    def test_hash_and_verify(self):
        hashed = hash_password("S3cure!passphrase")
        assert hashed != "S3cure!passphrase"
        assert verify_password("S3cure!passphrase", hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("correct-horse")
        assert not verify_password("wrong-battery", hashed)

    def test_hashes_are_salted(self):
        assert hash_password("same") != hash_password("same")


class TestTokens:
    def test_access_token_roundtrip(self):
        uid = uuid4()
        token = create_access_token(uid, "alice", "district_officer")
        payload = verify_token(token, "access")
        assert str(payload.sub) == str(uid)
        assert payload.username == "alice"
        assert payload.role == "district_officer"
        assert payload.iss == "geosentinel-ner"
        assert payload.aud == "geosentinel-api"
        assert payload.jti

    def test_refresh_token_type_mismatch_rejected(self):
        token = create_refresh_token(uuid4(), "bob", "citizen")
        with pytest.raises(ValueError, match="token type"):
            verify_token(token, "access")

    def test_expired_token_rejected(self):
        token = create_access_token(
            uuid4(), "carol", "admin", expires_delta=timedelta(seconds=-10)
        )
        with pytest.raises(ValueError, match="expired"):
            verify_token(token, "access")

    def test_tampered_token_rejected(self):
        token = create_access_token(uuid4(), "dave", "citizen")
        with pytest.raises(ValueError, match="Invalid token"):
            decode_token(token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb"))


class TestRBAC:
    def test_admin_has_all_permissions(self):
        assert check_permission("admin", "anything", "everything")

    def test_known_role_resource_action_allowed(self):
        assert check_permission("state_officer", "alerts", "write")
        assert check_permission("citizen", "reports", "create")

    def test_denied_actions(self):
        assert not check_permission("citizen", "users", "write")
        assert not check_permission("field_officer", "reports", "delete")

    def test_unknown_role_denied(self):
        assert not check_permission("superhero", "alerts", "read")

    def test_every_declared_role_has_entries(self):
        for role, perms in ROLE_PERMISSIONS.items():
            assert perms, f"role {role} has empty permission set"
