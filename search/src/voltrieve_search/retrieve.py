"""Query the knowledge base retrieve endpoint."""

import json
from dataclasses import dataclass, field

KNOWLEDGE_SOURCE_NAME = "voltrieve-docs-ks"
PARTS_KNOWLEDGE_BASE_NAME = "voltrieve-parts-kb"
PARTS_KNOWLEDGE_SOURCE_NAME = "voltrieve-parts-ks"


@dataclass
class Chunk:
    ref_id: str
    title: str
    content: str


@dataclass
class Reference:
    id: str
    doc_key: str
    reranker_score: float | None
    source_data: dict | None


@dataclass
class RetrieveResult:
    chunks: list[Chunk] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    activity: list[dict] = field(default_factory=list)
    partial: bool = False


def retrieve(
    client,
    kb_name: str,
    question: str,
    max_output_tokens: int = 5000,
    knowledge_source: str = KNOWLEDGE_SOURCE_NAME,
) -> RetrieveResult:
    body = {
        "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
        "knowledgeSourceParams": [
            {
                "kind": "searchIndex",
                "knowledgeSourceName": knowledge_source,
                "includeReferences": True,
                "includeReferenceSourceData": True,
            }
        ],
        "maxOutputSize": max_output_tokens,
        "includeActivity": True,
    }
    status, payload = client.post(f"/knowledgebases/{kb_name}/retrieve", body)
    return RetrieveResult(
        chunks=_parse_chunks(payload),
        references=[
            Reference(
                id=str(r.get("id")),
                doc_key=r.get("docKey", ""),
                reranker_score=r.get("rerankerScore"),
                source_data=r.get("sourceData"),
            )
            for r in payload.get("references") or []
        ],
        activity=payload.get("activity") or [],
        partial=status == 206,
    )


def _parse_chunks(payload: dict) -> list[Chunk]:
    messages = payload.get("response") or []
    content = messages[0].get("content") if messages else None
    if not content:
        return []
    try:
        items = json.loads(content[0].get("text") or "[]")
    except ValueError:
        return []
    return [
        Chunk(str(i.get("ref_id")), i.get("title", ""), i.get("content", ""))
        for i in items
        if isinstance(i, dict)
    ]
