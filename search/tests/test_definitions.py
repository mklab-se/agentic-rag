import json
from pathlib import Path

import pytest

from voltrieve_search.definitions import DEFINITION_ORDER, apply_all, render

DEFS = Path(__file__).parents[1] / "definitions"
VALUES = {
    "STORAGE_RESOURCE_ID": "/subscriptions/s/rg/x",
    "DOCS_CONTAINER": "voltrieve-docs",
    "FOUNDRY_ENDPOINT": "https://f.services.ai.azure.com",
    "EMBEDDING_DEPLOYMENT": "emb",
    "EMBEDDING_MODEL": "text-embedding-3-large",
    "FOUNDRY_OPENAI_ENDPOINT": "https://f.openai.azure.com",
    "CHAT_DEPLOYMENT": "chat",
    "CHAT_MODEL": "gpt-5.4-mini",
}


def test_render_replaces_all_placeholders():
    out = render((DEFS / "01-datasource.json").read_text(), VALUES)
    assert out["credentials"]["connectionString"] == "ResourceId=/subscriptions/s/rg/x;"


def test_render_fails_on_unreplaced_placeholder():
    with pytest.raises(KeyError):
        render('{"a": "{{MISSING}}"}', {})


def test_all_definitions_render_and_contain_no_keys():
    for f in sorted(DEFS.glob("*.json")):
        body = render(f.read_text(), VALUES)
        assert "apiKey" not in json.dumps(body) and "api-key" not in json.dumps(body)


def test_index_meets_knowledge_source_requirements():
    idx = render((DEFS / "02-index.json").read_text(), VALUES)
    key = next(f for f in idx["fields"] if f.get("key"))
    assert key["analyzer"] == "keyword"
    assert idx["semantic"]["defaultConfiguration"] == "semantic-config"
    vec = next(f for f in idx["fields"] if f["name"] == "text_vector")
    assert vec["dimensions"] == 3072 and vec["stored"] is False


def test_skillset_projections_do_not_map_key_fields():
    ss = render((DEFS / "03-skillset.json").read_text(), VALUES)
    names = {m["name"] for m in ss["indexProjections"]["selectors"][0]["mappings"]}
    assert "chunk_id" not in names and "parent_id" not in names
    assert {"model_slug", "doc_type", "chunk", "text_vector"} <= names


def test_apply_all_puts_in_order(fake_client):
    applied = apply_all(fake_client, VALUES, DEFS)
    assert applied == [
        "voltrieve-docs-ds",
        "voltrieve-docs-index",
        "voltrieve-docs-skillset",
        "voltrieve-docs-indexer",
        "voltrieve-docs-ks",
        "voltrieve-kb",
    ]
    assert [p.split("/")[1] for p, _ in fake_client.puts] == DEFINITION_ORDER


def test_knowledge_base_plans_queries_with_the_chat_model():
    kb = render((DEFS / "06-knowledge-base.json").read_text(), VALUES)
    params = kb["models"][0]["azureOpenAIParameters"]
    assert params == {
        "resourceUri": "https://f.openai.azure.com",
        "deploymentId": "chat",
        "modelName": "gpt-5.4-mini",
    }
    assert kb["retrievalReasoningEffort"]["kind"] == "low"
