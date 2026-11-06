"""The deployment definition: protocol, size, environment and image tag."""

from datetime import UTC, datetime

import pytest

import deploy

ENV = {
    "CHAT_DEPLOYMENT": "gpt-6.1-terra",
    "SEARCH_ENDPOINT": "https://srch.example",
    "DEALER_URL": "https://dealer.example",
    "DEALER_CLIENT_ID": "dealer-id",
    "API_PRINCIPAL_ID": "api-oid",
}


def test_definition_uses_invocations_protocol_and_small_size():
    definition = deploy.hosted_definition("acr.example/voltrieve/hosted:t1", ENV)
    assert [(p.protocol.value, p.version) for p in definition.protocol_versions] == [
        ("invocations", "2.0.0")
    ]
    assert definition.cpu == "0.5" and definition.memory == "1Gi"
    assert definition.container_configuration.image == "acr.example/voltrieve/hosted:t1"


def test_environment_has_no_reserved_names_and_defaults_the_caller_to_the_api():
    env = deploy.environment_variables(ENV)
    assert not [k for k in env if k.startswith("FOUNDRY_")]
    assert env["ALLOWED_CALLER_OID"] == "api-oid"
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING"] == "true"
    assert env["MODEL_DEPLOYMENT_NAME"] == "gpt-6.1-terra"


def test_allowed_caller_can_be_overridden_but_never_empty():
    assert deploy.environment_variables({**ENV, "ALLOWED_CALLER_OID": "x"})["ALLOWED_CALLER_OID"] == "x"
    with pytest.raises(SystemExit):
        deploy.environment_variables({**ENV, "API_PRINCIPAL_ID": ""})
    with pytest.raises(SystemExit):
        deploy.environment_variables({k: v for k, v in ENV.items() if k != "API_PRINCIPAL_ID"})


def test_sessions_are_suspended_after_the_minimum_idle_time():
    definition = deploy.hosted_definition("img", ENV)
    assert definition.session_configuration.idle_timeout_seconds.total_seconds() == 120


def test_tag_is_unique_per_second_and_carries_the_commit():
    tag = deploy.unique_tag(datetime(2026, 11, 4, 12, 30, 5, tzinfo=UTC), "abc1234")
    assert tag == "20261104123005-abc1234"
