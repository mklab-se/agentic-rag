# /// script
# requires-python = ">=3.12"
# ///
"""Count Python lines of code by concern, for docs/why-foundry.md.

    uv run scripts/measure_loc.py

A line counts when it holds code: blank lines, comment lines and docstrings do not count. Each
source line lands in exactly one group. `path::Name` takes one top-level class or function out of
a file; the plain path of the same file then takes what is left. The A, B and C columns say which
backend needs the group, so the totals show what each backend really runs. Only Python is counted:
Bicep, shell, TypeScript and JSON are not.
"""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = "agent_core/src/voltrieve_agent"
SEARCH = "search/src/voltrieve_search"


@dataclass(frozen=True)
class Group:
    concern: str
    needed_by: str  # any of "ABC"
    sources: tuple[str, ...]


AGENT_GROUPS = (
    Group("Orchestration loop and events", "ABC", (f"{CORE}/loop.py", f"{CORE}/events.py")),
    Group("Instructions (system prompt)", "ABC", (f"{CORE}/instructions.py",)),
    Group("Model client (Responses streaming)", "ABC", (f"{CORE}/model.py",)),
    Group("Tool set (validate, authorize, run)", "ABC", (f"{CORE}/tools.py",)),
    Group("Server tool definitions", "ABC", (f"{CORE}/server_tools.py",)),
    Group("Dealer client", "ABC", (f"{CORE}/dealer.py",)),
    Group(
        "Knowledge base client (retrieve)",
        "BC",
        (f"{CORE}/knowledge.py", f"{SEARCH}/retrieve.py", f"{SEARCH}/client.py"),
    ),
    Group("API contract (routes, schemas, SSE, app)", "ABC", (
        "api/app/routes.py", "api/app/schemas.py", "api/app/sse.py", "api/app/main.py",
        "api/app/settings.py",
    )),
    Group("Auth (token validation)", "ABC", ("api/app/auth.py",)),
    Group("Turn state and repair", "ABC", (
        "api/app/turns.py", "api/app/backends/base.py",
        "api/app/backends/loop.py::ConversationBackend",
    )),
    Group("Telemetry and logging", "ABC", ("api/app/telemetry.py", "api/app/logging_setup.py")),
    Group("Backend registry", "ABC", ("api/app/backends/__init__.py",)),
    Group("Loop host in the API (backends/loop.py)", "AB", ("api/app/backends/loop.py",)),
    Group("Prompt backend (backends/prompt.py)", "A", ("api/app/backends/prompt.py",)),
    Group("Prompt agent definitions (create_agents.py)", "A", ("agents/prompt/create_agents.py",)),
    Group("Hosted relay (backends/hosted.py)", "C", ("api/app/backends/hosted.py",)),
    Group("Hosted agent entry point (main.py)", "C", ("agents/hosted/main.py",)),
    Group("Hosted agent deployment (deploy.py)", "C", ("agents/hosted/deploy.py",)),
)

# Shared by all three, or not part of any agent: shown for scale, left out of the backend totals.
CONTEXT_GROUPS = (
    Group("CLI client", "", ("clients/cli/src",)),
    Group("Dealer service", "", ("services/dealer/app",)),
    Group("Search setup (rest of search/)", "", ("search/src",)),
    Group("Entra setup", "", ("infra/scripts/entra/src",)),
    Group("Demo and test scripts", "", ("scripts", "agents/prompt/demo_rejection.py", "tests/grounding")),
    Group("Automated tests", "", (
        "agent_core/tests", "api/tests", "agents/hosted/tests", "clients/cli/tests",
        "services/dealer/tests", "search/tests", "infra/scripts/entra/tests", "tests/contract",
    )),
)


def code_lines(source: str) -> set[int]:
    """Line numbers holding code: not blank, not a comment, not a docstring."""
    lines: set[int] = set()
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
            tokenize.ENCODING, tokenize.ENDMARKER}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type not in skip:
            lines.update(range(token.start[0], token.end[0] + 1))
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                lines.difference_update(range(first.lineno, first.end_lineno + 1))
    return lines


def symbol_lines(path: Path, name: str) -> set[int]:
    """The lines of one top-level class or function, decorators included."""
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if getattr(node, "name", None) == name:
            start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
            return set(range(start, node.end_lineno + 1))
    raise SystemExit(f"{path}: no top-level {name}")


def python_files(source: str) -> list[Path]:
    path = ROOT / source
    if path.is_dir():
        return [p for p in sorted(path.rglob("*.py")) if ".venv" not in p.parts]
    return [path]


def measure(groups: tuple[Group, ...], claimed: dict[Path, set[int]]) -> dict[str, int]:
    """Count each group. `claimed` keeps a line from being counted twice."""
    counts = dict.fromkeys((g.concern for g in groups), 0)

    def take(concern: str, path: Path, lines: set[int]) -> None:
        fresh = lines - claimed.setdefault(path, set())
        claimed[path] |= fresh
        counts[concern] += len(fresh)

    for group in groups:  # symbols first, so the plain path gets what is left
        for source in group.sources:
            if "::" in source:
                file, name = source.split("::")
                path = ROOT / file
                take(group.concern, path, code_lines(path.read_text()) & symbol_lines(path, name))
    for group in groups:
        for source in group.sources:
            if "::" not in source:
                for path in python_files(source):
                    take(group.concern, path, code_lines(path.read_text()))
    return counts


def main() -> None:
    claimed: dict[Path, set[int]] = {}
    agent = measure(AGENT_GROUPS, claimed)
    context = measure(CONTEXT_GROUPS, claimed)

    print("| Concern | Lines | A | B | C |")
    print("| --- | ---: | --- | --- | --- |")
    for group in AGENT_GROUPS:
        marks = " | ".join("x" if b in group.needed_by else "" for b in "ABC")
        print(f"| {group.concern} | {agent[group.concern]} | {marks} |")
    totals = {b: sum(agent[g.concern] for g in AGENT_GROUPS if b in g.needed_by) for b in "ABC"}
    print(f"| **Total the backend runs** | {sum(agent.values())} "
          f"| {totals['A']} | {totals['B']} | {totals['C']} |")
    print("\nFor scale, not part of the totals above:\n")
    print("| Other Python | Lines |")
    print("| --- | ---: |")
    for group in CONTEXT_GROUPS:
        print(f"| {group.concern} | {context[group.concern]} |")


if __name__ == "__main__":
    main()
