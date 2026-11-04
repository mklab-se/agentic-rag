# Evidence

Files from the live runs of 2026-11-04 against the deployed API. They are written by `scripts/runbook.py` (`<backend>.json`, `runbook-table.txt`) and `tests/grounding/check.py --save` (`grounding.txt`). `authorization-denied.txt` and `prompt-agent-rejection.txt` are the output of `scripts/denied_demo.py` and `agents/prompt/demo_rejection.py`.

Model output is kept verbatim, with two exceptions that the writers apply to every saved file (`write_evidence` in `scripts/voltrieve_client.py`):

- An em-dash becomes ` - `. Models write em-dashes and the repository does not use them.
- Absolute paths are removed (the repository root becomes a relative path, other home directory paths become `<path>`), so no file carries the name of the machine's user.

Nothing else is edited. In particular, the citation markers of the prompt agents (for example `【5:0†voltrieve-fjord-specifications.pdf】` in `grounding.txt`) are left as the run produced them. The runs predate the filter that rewrites them to ` (file)` in backend A, so the recorded answers of that backend show the markers a client would have seen then.

Evidence holds no tokens, usernames or URLs.

`runbook-table.txt` is the last full run on the final build. `loop-reruns.txt` has the earlier reruns of steps 7 and 10, including why step 10 was reworded.
