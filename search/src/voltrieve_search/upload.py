"""Upload the generated documents to blob storage with search metadata."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
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


@dataclass
class UploadResult:
    uploaded: int = 0
    stale: list[str] = field(default_factory=list)  # "container/blob" not in the manifest
    deleted: list[str] = field(default_factory=list)


def upload_documents(
    account_url: str,
    containers: dict[str, str],
    generated_dir: Path,
    credential,
    prune: bool = False,
    dry_run: bool = False,
    out: Callable[[str], None] = print,
) -> UploadResult:
    """Upload each document to the container of its collection (docs or parts).

    Blobs that are not in the manifest are stale. They are always reported; with prune they
    are deleted after the whole list has been printed, and with dry_run nothing changes.
    """
    manifest = json.loads((generated_dir / "manifest.json").read_text(encoding="utf-8"))
    service = BlobServiceClient(account_url, credential=credential)
    result = UploadResult()
    wanted: dict[str, set[str]] = {}
    for entry in manifest:
        wanted.setdefault(containers[entry["collection"]], set()).add(entry["file"])

    if not dry_run:
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
            result.uploaded += 1

    stale_by_container: dict[str, list[str]] = {}
    for container in dict.fromkeys(containers.values()):
        names = [b.name for b in service.get_container_client(container).list_blobs()]
        stale = sorted(n for n in names if n not in wanted.get(container, set()))
        stale_by_container[container] = stale
        result.stale += [f"{container}/{name}" for name in stale]
    for item in result.stale:
        out(f"stale: {item}")

    if prune and not dry_run:
        for container, stale in stale_by_container.items():
            container_client = service.get_container_client(container)
            for name in stale:
                if name in wanted.get(container, set()):  # never, by construction; kept as a guard
                    raise RuntimeError(f"refusing to delete {container}/{name}: it is in the manifest")
                container_client.delete_blob(name)
                result.deleted.append(f"{container}/{name}")
                out(f"deleted: {container}/{name}")
    return result


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def delete_index_entries(client, index_name: str, source_values: list[str]) -> int:
    """Delete the chunks whose source_path is one of the values (a blob URL or a blob name)."""
    if not source_values:
        return 0
    query = " or ".join(f"source_path eq {_quote(v)}" for v in source_values)
    _, payload = client.post(
        f"/indexes/{index_name}/docs/search",
        {"search": "*", "filter": query, "select": "chunk_id", "top": 1000},
    )
    keys = [hit["chunk_id"] for hit in payload.get("value", [])]
    if keys:
        client.post(
            f"/indexes/{index_name}/docs/index",
            {"value": [{"@search.action": "delete", "chunk_id": k} for k in keys]},
        )
    return len(keys)
