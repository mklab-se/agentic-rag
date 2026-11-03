"""Command line entry point. Subcommands are registered in SUBCOMMANDS."""

import argparse
import os
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential

from voltrieve_search.client import SearchRestClient
from voltrieve_search.definitions import apply_all

DEFINITIONS_DIR = Path(__file__).parents[2] / "definitions"
VALUE_KEYS = [
    "STORAGE_RESOURCE_ID",
    "DOCS_CONTAINER",
    "FOUNDRY_ENDPOINT",
    "EMBEDDING_DEPLOYMENT",
    "EMBEDDING_MODEL",
]


def make_client() -> SearchRestClient:
    credential = DefaultAzureCredential()
    return SearchRestClient(
        os.environ["SEARCH_ENDPOINT"],
        lambda: credential.get_token("https://search.azure.com/.default").token,
    )


def cmd_apply(args: argparse.Namespace) -> int:
    values = {key: os.environ[key] for key in VALUE_KEYS}
    for name in apply_all(make_client(), values, DEFINITIONS_DIR):
        print(f"applied {name}")
    return 0


SUBCOMMANDS = {"apply": (cmd_apply, "PUT all six definitions to the search service")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voltrieve-search")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in SUBCOMMANDS.items():
        sub.add_parser(name, help=help_text)
    args = parser.parse_args(argv)
    return SUBCOMMANDS[args.command][0](args)


if __name__ == "__main__":
    sys.exit(main())
