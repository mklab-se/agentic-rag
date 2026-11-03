"""The Voltrieve knowledge base, queried through Azure AI Search agentic retrieval."""

import asyncio
import json
from dataclasses import asdict

from voltrieve_search.client import SearchRestClient
from voltrieve_search.retrieve import RetrieveResult, retrieve

from voltrieve_agent.events import trace
from voltrieve_agent.tools import current_emit

KNOWLEDGE_BASE_NAME = "voltrieve-kb"
SEARCH_SCOPE = "https://search.azure.com/.default"


class KnowledgeBase:
    def __init__(self, search_endpoint: str, credential, kb_name: str = KNOWLEDGE_BASE_NAME):
        self._client = SearchRestClient(
            search_endpoint, lambda: credential.get_token(SEARCH_SCOPE).token
        )
        self._kb_name = kb_name

    async def search(self, query: str) -> str:
        result = await asyncio.to_thread(retrieve, self._client, self._kb_name, query)
        titles = _reference_titles(result)
        emit = current_emit.get()
        if emit is not None:
            await emit(
                trace(
                    "knowledge_base_retrieved",
                    "search",
                    f"{len(result.chunks)} chunks from {len(titles)} documents",
                    sub_queries=_sub_queries(result),
                    references=titles,
                    partial=result.partial,
                )
            )
        return json.dumps(
            {"chunks": [asdict(c) for c in result.chunks], "partial": result.partial}
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
