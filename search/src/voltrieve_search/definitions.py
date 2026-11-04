"""Loading, rendering and applying the numbered JSON definitions."""

import json
import re
from pathlib import Path
from typing import Protocol

# The file prefix selects the REST collection: each knowledge base is six numbered files in this
# order (01 to 06 for the documents, 07 to 12 for the spare parts).
DEFINITION_ORDER = [
    "datasources",
    "indexes",
    "skillsets",
    "indexers",
    "knowledgesources",
    "knowledgebases",
]

_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


class _Putter(Protocol):
    def put(self, path: str, body: dict) -> dict: ...


def render(template_text: str, values: dict[str, str]) -> dict:
    """Replace {{KEY}} placeholders and parse the result. Raises KeyError for unknown keys."""

    def substitute(match: re.Match) -> str:
        return values[match.group(1)]

    return json.loads(_PLACEHOLDER.sub(substitute, template_text))


def apply_all(client: _Putter, values: dict[str, str], definitions_dir: Path) -> list[str]:
    applied = []
    for file in sorted(definitions_dir.glob("[0-9][0-9]-*.json")):
        collection = DEFINITION_ORDER[(int(file.name[:2]) - 1) % len(DEFINITION_ORDER)]
        body = render(file.read_text(), values)
        client.put(f"/{collection}/{body['name']}", body)
        applied.append(body["name"])
    return applied
