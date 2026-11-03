import json

import voltrieve_search.upload as upload


class FakeContainer:
    def __init__(self):
        self.blobs = {}

    def upload_blob(self, name, handle, overwrite, metadata, content_settings):
        self.blobs[name] = content_settings.content_type


class FakeService:
    container = FakeContainer()

    def __init__(self, url, credential):
        pass

    def get_container_client(self, name):
        return self.container


def test_content_type_is_set_per_file(tmp_path, monkeypatch):
    names = ["a.md", "b.pdf", "c.docx"]
    for n in names:
        (tmp_path / n).write_bytes(b"x")
    manifest = [{"file": n, "doc_type": "spec", "model_slug": None} for n in names]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(upload, "BlobServiceClient", FakeService)
    assert upload.upload_documents("https://x", "c", tmp_path, None) == 3
    assert FakeService.container.blobs == {
        "a.md": "text/markdown",
        "b.pdf": "application/pdf",
        "c.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
