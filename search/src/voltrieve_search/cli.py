"""Command line entry point. Subcommands are registered in SUBCOMMANDS."""

import argparse
import json
import os
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential

from voltrieve_search.client import SearchApiError, SearchRestClient
from voltrieve_search.definitions import apply_all
from voltrieve_search.indexer import IndexerFailed, run_and_wait
from voltrieve_search.retrieve import retrieve
from voltrieve_search.smoke import SmokeQuestion, run_smoke
from voltrieve_search.upload import upload_documents

DEFINITIONS_DIR = Path(__file__).parents[2] / "definitions"
SMOKE_QUESTIONS = Path(__file__).parents[2] / "smoke-questions.json"
INDEXER_NAME = "voltrieve-docs-indexer"
KNOWLEDGE_BASE_NAME = "voltrieve-kb"
VALUE_KEYS = [
    "STORAGE_RESOURCE_ID",
    "DOCS_CONTAINER",
    "FOUNDRY_ENDPOINT",
    "EMBEDDING_DEPLOYMENT",
    "EMBEDDING_MODEL",
]


class MissingEnvironment(Exception):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingEnvironment(f"missing required environment variable {name}")
    return value


def make_client() -> SearchRestClient:
    credential = DefaultAzureCredential()
    return SearchRestClient(
        require_env("SEARCH_ENDPOINT"),
        lambda: credential.get_token("https://search.azure.com/.default").token,
    )


def cmd_apply(args: argparse.Namespace) -> int:
    values = {key: require_env(key) for key in VALUE_KEYS}
    for name in apply_all(make_client(), values, DEFINITIONS_DIR):
        print(f"applied {name}")
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    account_url = f"https://{require_env('STORAGE_ACCOUNT_NAME')}.blob.core.windows.net"
    count = upload_documents(
        account_url, require_env("DOCS_CONTAINER"), Path(args.generated), DefaultAzureCredential()
    )
    print(f"uploaded {count} documents")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    try:
        run = run_and_wait(make_client(), INDEXER_NAME)
    except IndexerFailed as failure:
        print(f"indexer failed: {failure}", file=sys.stderr)
        return 1
    print(f"indexer {run.status}: {run.items_processed} processed, {run.items_failed} failed")
    for warning in run.warnings:
        print(f"warning: {warning}")
    return 0


def cmd_retrieve(args: argparse.Namespace) -> int:
    result = retrieve(make_client(), KNOWLEDGE_BASE_NAME, args.question)
    print(
        json.dumps(
            {
                "partial": result.partial,
                "chunks": [vars(c) for c in result.chunks],
                "references": [vars(r) for r in result.references],
                "activity": result.activity,
            },
            indent=2,
        )
    )
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    questions = [SmokeQuestion(**q) for q in json.loads(SMOKE_QUESTIONS.read_text(encoding="utf-8"))]
    outcomes = run_smoke(make_client(), KNOWLEDGE_BASE_NAME, questions)
    failed = [o for o in outcomes if not o.passed]
    print(f"{len(outcomes) - len(failed)}/{len(outcomes)} smoke questions passed")
    return 1 if failed else 0


SUBCOMMANDS = {
    "apply": (cmd_apply, "PUT all six definitions to the search service"),
    "upload": (cmd_upload, "upload generated documents to blob storage"),
    "index": (cmd_index, "run the indexer and wait for the result"),
    "retrieve": (cmd_retrieve, "query the knowledge base and print chunks and references"),
    "smoke": (cmd_smoke, "run the smoke questions against the knowledge base"),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voltrieve-search")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in SUBCOMMANDS.items():
        command = sub.add_parser(name, help=help_text)
        if name == "upload":
            command.add_argument("--generated", default="data/generated")
        if name == "retrieve":
            command.add_argument("question")
    args = parser.parse_args(argv)
    try:
        return SUBCOMMANDS[args.command][0](args)
    except MissingEnvironment as error:
        print(str(error), file=sys.stderr)
        return 1
    except SearchApiError as error:
        print(f"search API error, {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
