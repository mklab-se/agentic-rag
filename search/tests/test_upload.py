import json

import voltrieve_search.upload as upload


class FakeContainer:
    def __init__(self, name="c", existing=(), events=None):
        self.url = f"https://x/{name}"
        self.blobs = {blob: "existing" for blob in existing}
        self.events = events if events is not None else []

    def upload_blob(self, name, handle, overwrite, metadata, content_settings):
        self.events.append(("upload", name))
        self.blobs[name] = content_settings.content_type

    def list_blobs(self):
        return [type("Blob", (), {"name": name})() for name in list(self.blobs)]

    def delete_blob(self, name):
        self.events.append(("delete", name))
        del self.blobs[name]


class FakeService:
    containers = {}

    def __init__(self, url, credential):
        pass

    def get_container_client(self, name):
        return self.containers.setdefault(name, FakeContainer())


def test_content_type_is_set_per_file(tmp_path, monkeypatch):
    names = ["a.md", "b.pdf", "c.docx"]
    for n in names:
        (tmp_path / n).write_bytes(b"x")
    manifest = [
        {"file": n, "doc_type": "spec", "model_slug": None, "collection": "docs"} for n in names
    ]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    FakeService.containers = {}
    monkeypatch.setattr(upload, "BlobServiceClient", FakeService)
    assert upload.upload_documents("https://x", {"docs": "c"}, tmp_path, None).uploaded == 3
    assert FakeService.containers["c"].blobs == {
        "a.md": "text/markdown",
        "b.pdf": "application/pdf",
        "c.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }


def test_each_collection_goes_to_its_own_container(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_bytes(b"x")
    (tmp_path / "b.md").write_bytes(b"x")
    manifest = [
        {"file": "a.md", "doc_type": "guide", "model_slug": None, "collection": "docs"},
        {"file": "b.md", "doc_type": "parts", "model_slug": None, "collection": "parts"},
    ]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    FakeService.containers = {}
    monkeypatch.setattr(upload, "BlobServiceClient", FakeService)
    upload.upload_documents("https://x", {"docs": "d", "parts": "p"}, tmp_path, None)
    assert set(FakeService.containers["d"].blobs) == {"a.md"}
    assert set(FakeService.containers["p"].blobs) == {"b.md"}


def manifest_dir(tmp_path, names):
    for n in names:
        (tmp_path / n).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / n).write_bytes(b"x")
    manifest = [{"file": n, "doc_type": "brochure", "model_slug": "fjord", "collection": "docs"} for n in names]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def with_container(monkeypatch, container):
    FakeService.containers = {"c": container}
    monkeypatch.setattr(upload, "BlobServiceClient", FakeService)


def test_never_deletes_a_manifest_blob(tmp_path, monkeypatch):
    names = ["sales/fjord/voltrieve-fjord-brochure.pdf", "voltrieve-service-guide.md"]
    container = FakeContainer(existing=names + ["voltrieve-fjord-brochure.docx"])
    with_container(monkeypatch, container)
    result = upload.upload_documents("https://x", {"docs": "c"}, manifest_dir(tmp_path, names), None,
                                     prune=True, out=lambda line: None)
    assert result.stale == ["c/voltrieve-fjord-brochure.docx"]
    assert result.deleted == ["c/voltrieve-fjord-brochure.docx"]
    assert set(container.blobs) == set(names)


def test_dry_run_deletes_nothing(tmp_path, monkeypatch):
    names = ["voltrieve-service-guide.md"]
    container = FakeContainer(existing=names + ["old.docx"])
    with_container(monkeypatch, container)
    printed = []
    result = upload.upload_documents("https://x", {"docs": "c"}, manifest_dir(tmp_path, names), None,
                                     prune=True, dry_run=True, out=printed.append)
    assert result.stale == ["c/old.docx"] and result.deleted == [] and result.uploaded == 0
    assert container.events == []
    assert any("old.docx" in line for line in printed)


def test_without_prune_stale_blobs_are_only_reported(tmp_path, monkeypatch):
    names = ["voltrieve-service-guide.md"]
    container = FakeContainer(existing=names + ["old.docx"])
    with_container(monkeypatch, container)
    result = upload.upload_documents("https://x", {"docs": "c"}, manifest_dir(tmp_path, names), None,
                                     out=lambda line: None)
    assert result.stale == ["c/old.docx"] and result.deleted == []
    assert "old.docx" in container.blobs


def test_lists_stale_before_deleting(tmp_path, monkeypatch):
    names = ["voltrieve-service-guide.md"]
    events = []
    container = FakeContainer(existing=names + ["old-a.docx", "old-b.pdf"], events=events)
    with_container(monkeypatch, container)
    upload.upload_documents("https://x", {"docs": "c"}, manifest_dir(tmp_path, names), None,
                            prune=True, out=lambda line: events.append(("print", line)))
    first_delete = next(i for i, e in enumerate(events) if e[0] == "delete")
    printed_before = [e[1] for e in events[:first_delete] if e[0] == "print"]
    assert any("old-a.docx" in line for line in printed_before)
    assert any("old-b.pdf" in line for line in printed_before)


class FakeSearch:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def post(self, path, body=None):
        self.calls.append((path, body))
        if path.endswith("/docs/search"):
            return 200, {"value": [{"chunk_id": k} for k in self.hits]}
        return 200, {}


def test_stale_index_entries_are_deleted_by_source_path():
    search = FakeSearch(["k1", "k2"])
    count = upload.delete_index_entries(search, "voltrieve-docs-index",
                                        ["https://x/c/it's.docx", "it's.docx"])
    assert count == 2
    path, body = search.calls[0]
    assert path == "/indexes/voltrieve-docs-index/docs/search"
    assert body["filter"] == "source_path eq 'https://x/c/it''s.docx' or source_path eq 'it''s.docx'"
    path, body = search.calls[1]
    assert path == "/indexes/voltrieve-docs-index/docs/index"
    assert body["value"] == [{"@search.action": "delete", "chunk_id": "k1"},
                             {"@search.action": "delete", "chunk_id": "k2"}]


def test_no_index_call_when_nothing_matches():
    search = FakeSearch([])
    assert upload.delete_index_entries(search, "voltrieve-docs-index", ["a.docx"]) == 0
    assert len(search.calls) == 1
