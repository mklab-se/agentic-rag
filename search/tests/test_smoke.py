import voltrieve_search.smoke as smoke
from voltrieve_search.retrieve import Reference, RetrieveResult
from voltrieve_search.smoke import SmokeQuestion, run_smoke


def ref(title, doc_type):
    return Reference(id="0", doc_key="k", reranker_score=3.0, source_data={"title": title, "doc_type": doc_type})


def test_smoke_passes_on_matching_reference(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "retrieve",
        lambda c, kb, q, knowledge_source: RetrieveResult([], [ref("voltrieve-fjord-specifications.pdf", "spec")], [], False),
    )
    assert run_smoke(None, [SmokeQuestion("q", "fjord-specifications", "spec")])[0].passed


def test_smoke_fails_on_wrong_doc_type(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "retrieve",
        lambda c, kb, q, knowledge_source: RetrieveResult([], [ref("voltrieve-fjord-brochure.docx", "brochure")], [], False),
    )
    assert not run_smoke(None, [SmokeQuestion("q", "fjord-specifications", "spec")])[0].passed


def test_cli_missing_env_var_exits_1_with_short_message(monkeypatch, capsys):
    from voltrieve_search.cli import main

    monkeypatch.delenv("SEARCH_ENDPOINT", raising=False)
    assert main(["retrieve", "q"]) == 1
    assert "SEARCH_ENDPOINT" in capsys.readouterr().err


def test_smoke_prints_activity_errors_when_partial(monkeypatch, capsys):
    monkeypatch.setattr(
        smoke,
        "retrieve",
        lambda c, kb, q, knowledge_source: RetrieveResult([], [], [{"type": "searchIndex", "error": {"message": "timeout"}}], True),
    )
    run_smoke(None, [SmokeQuestion("q", "x", "spec")])
    assert "timeout" in capsys.readouterr().out


def test_smoke_questions_name_document_types_that_exist():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    questions = json.loads((root / "search" / "smoke-questions.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "data" / "generated" / "manifest.json").read_text(encoding="utf-8"))
    docs = manifest["documents"] if isinstance(manifest, dict) else manifest
    types = {d["doc_type"] for d in docs}
    files = " ".join(Path(d["file"]).name for d in docs)
    for q in questions:
        assert q["expect_doc_type"] in types, q["question"]
        assert q["expect_title_contains"] in files, q["question"]
