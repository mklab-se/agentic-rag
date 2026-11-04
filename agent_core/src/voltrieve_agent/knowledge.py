"""The Voltrieve knowledge bases, queried through Azure AI Search agentic retrieval."""

import asyncio
import json
from dataclasses import asdict

from voltrieve_search.client import SearchApiError, SearchRestClient
from voltrieve_search.retrieve import (
    KNOWLEDGE_SOURCE_NAME,
    PARTS_KNOWLEDGE_BASE_NAME,
    PARTS_KNOWLEDGE_SOURCE_NAME,
    RetrieveResult,
    retrieve,
)

from voltrieve_agent.events import trace
from voltrieve_agent.tools import current_emit

KNOWLEDGE_BASE_NAME = "voltrieve-kb"
SEARCH_SCOPE = "https://search.azure.com/.default"
# Query planning spends model tokens, so a busy deployment answers a retrieve with 429.
RATE_LIMIT_RETRIES = 2
RATE_LIMIT_DELAY_SECONDS = 10.0


class KnowledgeBase:
    def __init__(
        self,
        search_endpoint: str,
        credential,
        kb_name: str = KNOWLEDGE_BASE_NAME,
        knowledge_source: str = KNOWLEDGE_SOURCE_NAME,
    ):
        self._client = SearchRestClient(
            search_endpoint, lambda: credential.get_token(SEARCH_SCOPE).token
        )
        self._kb_name = kb_name
        self._knowledge_source = knowledge_source

    async def search(self, query: str) -> str:
        result = await self._retrieve(query)
        titles = _reference_titles(result)
        emit = current_emit.get()
        if emit is not None:
            await emit(
                trace(
                    "knowledge_base_retrieved",
                    "search",
                    f"{self._kb_name}: {len(result.chunks)} chunks from {len(titles)} documents",
                    knowledge_base=self._kb_name,
                    sub_queries=_sub_queries(result),
                    references=titles,
                    partial=result.partial,
                )
            )
        return json.dumps(
            {"chunks": [asdict(c) for c in result.chunks], "partial": result.partial}
        )

    async def _retrieve(self, query: str) -> RetrieveResult:
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                return await asyncio.to_thread(
                    retrieve,
                    self._client,
                    self._kb_name,
                    query,
                    knowledge_source=self._knowledge_source,
                )
            except SearchApiError as exc:
                if exc.status != 429 or attempt == RATE_LIMIT_RETRIES:
                    raise
                await asyncio.sleep(RATE_LIMIT_DELAY_SECONDS * (attempt + 1))
        raise AssertionError("unreachable")


def parts_knowledge_base(search_endpoint: str, credential) -> KnowledgeBase:
    return KnowledgeBase(
        search_endpoint, credential, PARTS_KNOWLEDGE_BASE_NAME, PARTS_KNOWLEDGE_SOURCE_NAME
    )


def _sub_queries(result: RetrieveResult) -> list[str]:
    queries = []
    for item in result.activity:
        search = (item.get("searchIndexArguments") or {}).get("search")
        if item.get("type") == "searchIndex" and search:
            queries.append(search)
    return queries


def _reference_titles(result: RetrieveResult) -> list[str]:
    by_ref = {c.ref_id: c.title for c in result.chunks}
    titles: list[str] = []
    for ref in result.references:
        title = by_ref.get(ref.id) or (ref.source_data or {}).get("title") or ref.doc_key
        if title and title not in titles:
            titles.append(title)
    return titles
