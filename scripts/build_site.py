# /// script
# requires-python = ">=3.12"
# dependencies = ["mkdocs-material"]
# ///
"""Build the documentation site into site/. README.md becomes the home page.

    uv run scripts/build_site.py

Links into docs/ become site links, and links to code become links to the repository.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
REPOSITORY = "https://github.com/mklab-se/agentic-rag/blob/main/"
INDEX = ROOT / "docs" / "index.md"


def relink(match: re.Match) -> str:
    bang, text, target = match.groups()
    if target.startswith(("http", "#")):
        return match.group(0)
    if target.startswith("docs/superpowers/"):
        return f"{bang}[{text}]({REPOSITORY}{target})"
    if target == "docs/evidence/":
        return f"{bang}[{text}](evidence/README.md)"
    if target.startswith("docs/"):
        return f"{bang}[{text}]({target.removeprefix('docs/')})"
    return f"{bang}[{text}]({REPOSITORY}{target})"


def main() -> int:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    INDEX.write_text(re.sub(r"(!?)\[([^\]]*)\]\(([^)]+)\)", relink, text), encoding="utf-8")
    return subprocess.run(["mkdocs", "build", "--clean"], cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
