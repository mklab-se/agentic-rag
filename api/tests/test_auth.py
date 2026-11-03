import jwt
import pytest

from app.auth import AuthError, TokenValidator


async def test_valid_token(validator, make_token):
    claims = await validator.validate(f"Bearer {make_token()}")
    assert claims.oid == "oid-anna" and "Chat.User" in claims.roles


async def test_api_audience_accepted(validator, make_token):
    import os

    assert await validator.validate(f"Bearer {make_token(aud='api://' + os.environ['API_CLIENT_ID'])}")


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer", "Bearer a b", "justatoken"])
async def test_missing_or_malformed_header_is_401(validator, header):
    with pytest.raises(AuthError) as e:
        await validator.validate(header)
    assert e.value.status_code == 401


async def test_bare_token_without_scheme_is_401(validator, make_token):
    with pytest.raises(AuthError) as e:
        await validator.validate(make_token())
    assert e.value.status_code == 401


@pytest.mark.parametrize("overrides", [{"aud": "other"}, {"exp_delta_seconds": -60}, {"kid": "x"}])
async def test_bad_tokens_are_401(validator, make_token, overrides):
    with pytest.raises(AuthError) as e:
        await validator.validate(f"Bearer {make_token(**overrides)}")
    assert e.value.status_code == 401


async def test_missing_role_is_403(validator, make_token):
    with pytest.raises(AuthError) as e:
        await validator.validate(f"Bearer {make_token(roles=['Other'])}")
    assert e.value.status_code == 403


@pytest.mark.parametrize("scp", ["", "other", "access_as_user_not"])
async def test_missing_scope_is_403(validator, make_token, scp):
    with pytest.raises(AuthError) as e:
        await validator.validate(f"Bearer {make_token(scp=scp)}")
    assert e.value.status_code == 403


async def test_forged_kids_refetch_once_per_cooldown(make_token, jwks):
    import os

    calls = []

    def fetch():
        calls.append(1)
        return jwks

    v = TokenValidator(os.environ["TENANT_ID"], os.environ["API_CLIENT_ID"], jwks_fetcher=fetch)
    await v.validate(f"Bearer {make_token()}")
    for _ in range(3):
        with pytest.raises(AuthError):
            await v.validate(f"Bearer {make_token(kid='nope')}")
    assert len(calls) == 2


async def test_non_rsa_keys_in_jwks_are_ignored(make_token, jwks):
    import os

    ec = {"kty": "EC", "crv": "P-256", "x": "AAAA", "y": "AAAA", "kid": "ec", "use": "sig"}
    v = TokenValidator(
        os.environ["TENANT_ID"],
        os.environ["API_CLIENT_ID"],
        jwks_fetcher=lambda: {"keys": [ec, *jwks["keys"]]},
    )
    assert await v.validate(f"Bearer {make_token()}")
    with pytest.raises(AuthError) as e:
        await v.validate(f"Bearer {make_token(kid='ec')}")
    assert e.value.status_code == 401


def _forge(claims_overrides=None, key=None, alg="RS256", headers=None, drop=()):
    import os
    import time

    now = int(time.time())
    claims = {
        "iss": f"https://login.microsoftonline.com/{os.environ['TENANT_ID']}/v2.0",
        "aud": os.environ["API_CLIENT_ID"],
        "scp": "access_as_user",
        "roles": ["Chat.User"],
        "oid": "oid-anna",
        "nbf": now - 10,
        "exp": now + 300,
        **(claims_overrides or {}),
    }
    for k in drop:
        claims.pop(k)
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": "test", **(headers or {})})


async def test_wrong_key_with_valid_kid_is_401(validator):
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(AuthError) as e:
        await validator.validate(f"Bearer {_forge(key=other)}")
    assert e.value.status_code == 401


@pytest.mark.parametrize(
    "overrides,drop",
    [
        ({"iss": "https://login.microsoftonline.com/other/v2.0"}, ()),
        ({"nbf": 4_000_000_000, "exp": 4_000_000_100}, ()),
        ({}, ("nbf",)),
        ({}, ("oid",)),
    ],
)
async def test_bad_claims_are_401(validator, rsa_key, overrides, drop):
    with pytest.raises(AuthError) as e:
        await validator.validate(f"Bearer {_forge(overrides, rsa_key, drop=drop)}")
    assert e.value.status_code == 401


async def test_alg_none_is_401(validator):
    import base64
    import json

    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    token = f"{b64({'alg': 'none', 'kid': 'test'})}.{b64({'aud': 'x', 'oid': 'o'})}."
    with pytest.raises(AuthError) as e:
        await validator.validate(f"Bearer {token}")
    assert e.value.status_code == 401


async def test_hs256_is_401(validator):
    token = _forge(key="s" * 48, alg="HS256")
    with pytest.raises(AuthError) as e:
        await validator.validate(f"Bearer {token}")
    assert e.value.status_code == 401
