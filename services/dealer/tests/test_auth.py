import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import AuthError, TokenValidator


async def test_valid_v2_token(validator, make_token):
    claims = await validator.validate(make_token())
    assert "Dealer.Access" in claims.roles


async def test_v1_style_audience_accepted(validator, make_token, client_id):
    claims = await validator.validate(make_token(aud=f"api://{client_id}"))
    assert claims.oid


async def test_wrong_audience_rejected(validator, make_token):
    with pytest.raises(AuthError) as e:
        await validator.validate(make_token(aud="other"))
    assert e.value.status_code == 401


async def test_missing_role_is_403(validator, make_token):
    with pytest.raises(AuthError) as e:
        await validator.validate(make_token(roles=[]))
    assert e.value.status_code == 403


async def test_expired_token_rejected(validator, make_token):
    with pytest.raises(AuthError):
        await validator.validate(make_token(exp_delta_seconds=-60))


async def test_unknown_kid_triggers_one_refetch(make_token, jwks, client_id, tenant_id):
    calls = []

    def fetch():
        calls.append(1)
        return jwks

    v = TokenValidator(tenant_id, client_id, "Dealer.Access", jwks_fetcher=fetch)
    await v.validate(make_token())
    with pytest.raises(AuthError):
        await v.validate(make_token(kid="nope"))
    assert len(calls) == 2


async def test_bearer_header_value_accepted(validator, make_token):
    claims = await validator.validate(f"Bearer {make_token()}")
    assert claims.app_id


@pytest.mark.parametrize("header", ["", "Basic abc", "Bearer", "Bearer a b"])
async def test_missing_or_malformed_header_is_401(validator, header):
    with pytest.raises(AuthError) as e:
        await validator.validate(header)
    assert e.value.status_code == 401


async def test_garbage_token_is_401(validator):
    with pytest.raises(AuthError) as e:
        await validator.validate("not-a-jwt")
    assert e.value.status_code == 401


async def test_bad_signature_is_401(validator, tenant_id, client_id):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {
            "iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            "aud": client_id,
            "roles": ["Dealer.Access"],
            "oid": "x",
            "exp": 4102444800,
        },
        other,
        algorithm="RS256",
        headers={"kid": "test"},
    )
    with pytest.raises(AuthError) as e:
        await validator.validate(token)
    assert e.value.status_code == 401


async def test_wrong_issuer_is_401(validator, make_token, rsa_key, client_id):
    token = jwt.encode(
        {"iss": "https://evil.example/v2.0", "aud": client_id, "roles": ["Dealer.Access"],
         "oid": "x", "exp": 4102444800},
        rsa_key,
        algorithm="RS256",
        headers={"kid": "test"},
    )
    with pytest.raises(AuthError) as e:
        await validator.validate(token)
    assert e.value.status_code == 401


async def test_alg_none_is_401(validator, tenant_id, client_id):
    token = jwt.encode(
        {"iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0", "aud": client_id,
         "roles": ["Dealer.Access"], "oid": "x", "exp": 4102444800},
        None,
        algorithm="none",
        headers={"kid": "test"},
    )
    with pytest.raises(AuthError) as e:
        await validator.validate(token)
    assert e.value.status_code == 401


async def test_not_yet_valid_is_401(validator, make_token, rsa_key, tenant_id, client_id):
    token = jwt.encode(
        {"iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0", "aud": client_id,
         "roles": ["Dealer.Access"], "oid": "x", "nbf": 4102444800, "exp": 4102448400},
        rsa_key,
        algorithm="RS256",
        headers={"kid": "test"},
    )
    with pytest.raises(AuthError) as e:
        await validator.validate(token)
    assert e.value.status_code == 401


async def test_consecutive_unknown_kids_refetch_only_once(make_token, jwks, client_id, tenant_id):
    calls = []

    def fetch():
        calls.append(1)
        return jwks

    v = TokenValidator(tenant_id, client_id, "Dealer.Access", jwks_fetcher=fetch)
    await v.validate(make_token())
    for _ in range(3):
        with pytest.raises(AuthError) as e:
            await v.validate(make_token(kid="nope"))
        assert e.value.status_code == 401
    assert len(calls) == 2


async def test_valid_token_not_blocked_by_slow_fetch(make_token, jwks, client_id, tenant_id):
    import asyncio
    import time

    delay = 0.0

    def fetch():
        time.sleep(delay)
        return jwks

    v = TokenValidator(tenant_id, client_id, "Dealer.Access", jwks_fetcher=fetch)
    await v.validate(make_token())
    delay = 0.5
    forged = asyncio.create_task(v.validate(make_token(kid="nope")))
    await asyncio.sleep(0.05)
    start = time.monotonic()
    await v.validate(make_token())
    assert time.monotonic() - start < 0.2
    with pytest.raises(AuthError):
        await forged


@pytest.mark.parametrize("missing", ["exp", "aud"])
async def test_token_missing_required_claim_is_401(validator, rsa_key, tenant_id, client_id, missing):
    claims = {
        "iss": f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        "aud": client_id,
        "roles": ["Dealer.Access"],
        "oid": "x",
        "exp": 4102444800,
    }
    del claims[missing]
    token = jwt.encode(claims, rsa_key, algorithm="RS256", headers={"kid": "test"})
    with pytest.raises(AuthError) as e:
        await validator.validate(token)
    assert e.value.status_code == 401
