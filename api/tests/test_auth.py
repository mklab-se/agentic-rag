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
