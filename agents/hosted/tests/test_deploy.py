"""The deployment definition: protocol, size, environment and image tag."""

from datetime import UTC, datetime

import deploy

ENV = {
    "CHAT_DEPLOYMENT": "gpt-5.4-mini",
    "SEARCH_ENDPOINT": "https://srch.example",
    "DEALER_URL": "https://dealer.example",
    "DEALER_CLIENT_ID": "dealer-id",
    "TENANT_ID": "tenant",
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
    assert env["MODEL_DEPLOYMENT_NAME"] == "gpt-5.4-mini"


def test_allowed_caller_can_be_overridden_or_emptied():
    assert deploy.environment_variables({**ENV, "ALLOWED_CALLER_OID": "x"})["ALLOWED_CALLER_OID"] == "x"
    assert deploy.environment_variables({**ENV, "ALLOWED_CALLER_OID": ""})["ALLOWED_CALLER_OID"] == ""


def test_tag_is_unique_per_second_and_carries_the_commit():
    tag = deploy.unique_tag(datetime(2026, 11, 4, 12, 30, 5, tzinfo=UTC), "abc1234")
    assert tag == "20261104123005-abc1234"
