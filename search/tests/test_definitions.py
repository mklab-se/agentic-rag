import json
from pathlib import Path

import pytest

from voltrieve_search.definitions import DEFINITION_ORDER, apply_all, render

DEFS = Path(__file__).parents[1] / "definitions"
VALUES = {
    "STORAGE_RESOURCE_ID": "/subscriptions/s/rg/x",
    "DOCS_CONTAINER": "voltrieve-docs",
    "PARTS_CONTAINER": "voltrieve-parts",
    "FOUNDRY_ENDPOINT": "https://f.services.ai.azure.com",
    "EMBEDDING_DEPLOYMENT": "emb",
    "EMBEDDING_MODEL": "text-embedding-3-large",
    "FOUNDRY_OPENAI_ENDPOINT": "https://f.openai.azure.com",
    "PLANNING_DEPLOYMENT": "chat",
    "PLANNING_MODEL": "gpt-5.4-mini",
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
        "voltrieve-parts-ds",
        "voltrieve-parts-index",
        "voltrieve-parts-skillset",
        "voltrieve-parts-indexer",
        "voltrieve-parts-ks",
        "voltrieve-parts-kb",
    ]
    assert [p.split("/")[1] for p, _ in fake_client.puts] == DEFINITION_ORDER * 2


def test_parts_definitions_never_touch_the_docs_resources():
    names = ["07-parts-datasource", "08-parts-index", "09-parts-skillset", "10-parts-indexer",
             "11-parts-knowledge-source", "12-parts-knowledge-base"]
    for name in names:
        assert "voltrieve-docs" not in (DEFS / f"{name}.json").read_text()
    assert render((DEFS / "07-parts-datasource.json").read_text(), VALUES)["container"] == {
        "name": "voltrieve-parts"
    }


def test_knowledge_base_plans_queries_with_the_chat_model():
    kb = render((DEFS / "06-knowledge-base.json").read_text(), VALUES)
    params = kb["models"][0]["azureOpenAIParameters"]
    assert params == {
        "resourceUri": "https://f.openai.azure.com",
        "deploymentId": "chat",
        "modelName": "gpt-5.4-mini",
    }
    assert kb["retrievalReasoningEffort"]["kind"] == "low"


def test_documents_descriptions_name_the_sales_folders():
    import json
    from pathlib import Path

    folder = Path(__file__).resolve().parents[1] / "definitions"
    for name in ("01-datasource.json", "02-index.json", "05-knowledge-source.json", "06-knowledge-base.json"):
        description = json.loads((folder / name).read_text(encoding="utf-8"))["description"]
        for kind in ("price list", "accessories", "warranty", "charging guide", "service guide"):
            assert kind in description, (name, kind)


def test_parts_descriptions_name_the_new_catalogs():
    import json
    from pathlib import Path

    folder = Path(__file__).resolve().parents[1] / "definitions"
    for name in ("07-parts-datasource.json", "08-parts-index.json", "11-parts-knowledge-source.json",
                 "12-parts-knowledge-base.json"):
        description = json.loads((folder / name).read_text(encoding="utf-8"))["description"]
        for kind in ("tyres", "interior"):
            assert kind in description, (name, kind)
