"""Upload the generated documents to blob storage with search metadata."""

import json
from pathlib import Path

from azure.storage.blob import BlobServiceClient, ContentSettings

NO_MODEL_SLUG = "all"
CONTENT_TYPES = {
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _content_type(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix not in CONTENT_TYPES:
        raise ValueError(f"no content type for {file_name}")
    return CONTENT_TYPES[suffix]


def upload_documents(
    account_url: str, containers: dict[str, str], generated_dir: Path, credential
) -> int:
    """Upload each document to the container of its collection (docs or parts)."""
    manifest = json.loads((generated_dir / "manifest.json").read_text(encoding="utf-8"))
    service = BlobServiceClient(account_url, credential=credential)
    for entry in manifest:
        container_client = service.get_container_client(containers[entry["collection"]])
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
                content_settings=ContentSettings(content_type=_content_type(entry["file"])),
            )
    return len(manifest)
