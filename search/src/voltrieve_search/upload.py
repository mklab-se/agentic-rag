"""Upload the generated documents to blob storage with search metadata."""

import json
from pathlib import Path

from azure.storage.blob import BlobServiceClient, ContentSettings

NO_MODEL_SLUG = "all"


def upload_documents(account_url: str, container: str, generated_dir: Path, credential) -> int:
    manifest = json.loads((generated_dir / "manifest.json").read_text(encoding="utf-8"))
    container_client = BlobServiceClient(account_url, credential=credential).get_container_client(
        container
    )
    for entry in manifest:
        metadata = {
            "model_slug": entry.get("model_slug") or NO_MODEL_SLUG,
            "doc_type": entry["doc_type"],
        }
        with (generated_dir / entry["file"]).open("rb") as handle:
            container_client.upload_blob(
                entry["file"],
                handle,
                overwrite=True,
                metadata=metadata,
                content_settings=ContentSettings(),
            )
    return len(manifest)
