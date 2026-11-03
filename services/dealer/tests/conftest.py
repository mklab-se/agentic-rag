import os

os.environ.setdefault("TENANT_ID", "00000000-0000-0000-0000-0000000000aa")
os.environ.setdefault("DEALER_CLIENT_ID", "00000000-0000-0000-0000-0000000000bb")

import time  # noqa: E402

import jwt  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from app.auth import TokenValidator  # noqa: E402
from app.settings import Settings  # noqa: E402


@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def tenant_id() -> str:
    return os.environ["TENANT_ID"]


@pytest.fixture(scope="session")
def client_id() -> str:
    return os.environ["DEALER_CLIENT_ID"]


@pytest.fixture(scope="session")
def jwks(rsa_key) -> dict:
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(rsa_key.public_key(), as_dict=True)
    jwk.update({"kid": "test", "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


@pytest.fixture
def make_token(rsa_key, tenant_id, client_id):
    def _make(**overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            "aud": overrides.get("aud", client_id),
            "roles": overrides.get("roles", ["Dealer.Access"]),
            "oid": "11111111-1111-1111-1111-111111111111",
            "azp": "22222222-2222-2222-2222-222222222222",
            "nbf": now - 10,
            "exp": now + overrides.get("exp_delta_seconds", 300),
        }
        return jwt.encode(
            claims, rsa_key, algorithm="RS256", headers={"kid": overrides.get("kid", "test")}
        )

    return _make


@pytest.fixture
def validator(tenant_id, client_id, jwks) -> TokenValidator:
    return TokenValidator(tenant_id, client_id, "Dealer.Access", jwks_fetcher=lambda: jwks)


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def auth_header(make_token) -> dict:
    return {"Authorization": f"Bearer {make_token()}"}
