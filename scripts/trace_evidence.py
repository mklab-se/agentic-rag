# /// script
# requires-python = ">=3.12"
# ///
"""Runbook step 12: one turn per backend, followed through Application Insights by trace id.

    uv run scripts/trace_evidence.py [--hours 2]

Finds the latest dealer stock turn from scripts/runbook.py per backend and counts telemetry per
service. Writes docs/evidence/application-insights.txt. Needs az and AZURE_RESOURCE_GROUP.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

EVIDENCE = Path(__file__).parent.parent / "docs" / "evidence" / "application-insights.txt"


def query(group: str, app: str, kql: str) -> list[list]:
    out = subprocess.run(
        ["az", "monitor", "app-insights", "query", "-g", group, "--app", app,
         "--analytics-query", kql, "-o", "json"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)["tables"][0]["rows"]


def resource_group_app() -> tuple[str, str]:
    group = os.environ["AZURE_RESOURCE_GROUP"]
    app = subprocess.run(
        ["az", "resource", "list", "-g", group, "--resource-type", "Microsoft.Insights/components",
         "--query", "[0].name", "-o", "tsv"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return group, app


def trace_counts(group: str, app: str, backend: str, hours: int) -> list[list]:
    """Telemetry per service for the latest runbook step 8 turn of a backend."""
    rows = query(group, app, f"requests | where timestamp > ago({hours}h) "
                 f"and name == 'POST /chat' | where customDimensions has 'runbook-{backend}-8' "
                 "| top 1 by timestamp | project operation_Id")
    if not rows:
        return []
    return query(group, app, f"union requests, dependencies, traces "
                 f"| where timestamp > ago({hours}h) and operation_Id == '{rows[0][0]}' "
                 "| summarize n=count() by cloud_RoleName, itemType | order by cloud_RoleName asc")


def write_report(counts: dict[str, list[list]]) -> str:
    lines = []
    for backend, rows in counts.items():
        lines.append(f"== backend {backend}, step 8 (dealer stock question)")
        lines.extend(f"{role:<20} {kind:<12} {n}" for role, kind, n in rows)
        if not rows:
            lines.append("no trace found")
    text = "\n".join(lines) + "\n"
    EVIDENCE.write_text(text, encoding="utf-8")
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=2)
    args = parser.parse_args()
    group, app = resource_group_app()
    print(write_report({b: trace_counts(group, app, b, args.hours) for b in ("loop", "prompt", "hosted")}))


if __name__ == "__main__":
    main()
