import json

import voltrieve_search.upload as upload


class FakeContainer:
    def __init__(self):
        self.blobs = {}

    def upload_blob(self, name, handle, overwrite, metadata, content_settings):
        self.blobs[name] = content_settings.content_type


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
    monkeypatch.setattr(upload, "BlobServiceClient", FakeService)
    assert upload.upload_documents("https://x", {"docs": "c"}, tmp_path, None) == 3
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
