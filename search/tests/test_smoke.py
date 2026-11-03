import voltrieve_search.smoke as smoke
from voltrieve_search.retrieve import Reference, RetrieveResult
from voltrieve_search.smoke import SmokeQuestion, run_smoke


def ref(title, doc_type):
    return Reference(id="0", doc_key="k", reranker_score=3.0, source_data={"title": title, "doc_type": doc_type})


def test_smoke_passes_on_matching_reference(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "retrieve",
        lambda c, kb, q: RetrieveResult([], [ref("voltrieve-fjord-specifications.pdf", "spec")], [], False),
    )
    assert run_smoke(None, "kb", [SmokeQuestion("q", "fjord-specifications", "spec")])[0].passed


def test_smoke_fails_on_wrong_doc_type(monkeypatch):
    monkeypatch.setattr(
        smoke,
        "retrieve",
        lambda c, kb, q: RetrieveResult([], [ref("voltrieve-fjord-brochure.docx", "brochure")], [], False),
    )
    assert not run_smoke(None, "kb", [SmokeQuestion("q", "fjord-specifications", "spec")])[0].passed


def test_cli_missing_env_var_exits_1_with_short_message(monkeypatch, capsys):
    from voltrieve_search.cli import main

    monkeypatch.delenv("SEARCH_ENDPOINT", raising=False)
    assert main(["retrieve", "q"]) == 1
    assert "SEARCH_ENDPOINT" in capsys.readouterr().err


def test_smoke_prints_activity_errors_when_partial(monkeypatch, capsys):
    monkeypatch.setattr(
        smoke,
        "retrieve",
        lambda c, kb, q: RetrieveResult([], [], [{"type": "searchIndex", "error": {"message": "timeout"}}], True),
    )
    run_smoke(None, "kb", [SmokeQuestion("q", "x", "spec")])
    assert "timeout" in capsys.readouterr().out
