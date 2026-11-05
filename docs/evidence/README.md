# Evidence

Files from the live runs of 2026-11-04 against the deployed API. They are written by `scripts/runbook.py` (`<backend>.json`, `runbook-table.txt`) and `tests/grounding/check.py --save` (`grounding.txt`). `authorization-denied.txt` and `prompt-agent-rejection.txt` are the output of `scripts/denied_demo.py` and `agents/prompt/demo_rejection.py`.

Model output is kept verbatim, with two exceptions that the writers apply to every saved file (`write_evidence` in `scripts/voltrieve_client.py`):

- An em-dash becomes ` - `. Models write em-dashes and the repository does not use them.
- Absolute paths are removed (the repository root becomes a relative path, other home directory paths become `<path>`), so no file carries the name of the machine's user.

Nothing else is edited. In particular, the citation markers of the prompt agents (for example `【5:0†voltrieve-fjord-specifications.pdf】` in `grounding.txt`) are left as the run produced them. The runs predate the filter that rewrites them to ` (file)` in backend A, so the recorded answers of that backend show the markers a client would have seen then.

Evidence holds no tokens, usernames or URLs.

`runbook-table.txt` is the last full run on the final build.

`routing.txt` and `routing.json` are the last full run of `tests/routing/check.py`, one question at a time. `routing-after-catalog-fix.txt` is the brake questions after brake fluid moved into the brake catalog. `routing-load.txt` is a run of the four brake questions with `--workers 4`. `parallel-setting.txt` comes from `agents/prompt/demo_parallel_setting.py`. `prompt-extra-steps.txt` holds traces of the prompt agent on job questions.

`prompt-journey.txt` comes from `scripts/prompt_journey.py`. `model-comparison.txt` and the runs in `models/` come from `scripts/model_costs.py` and the comparison scripts. `curated-latency.txt` and its two JSON files come from `scripts/curated_latency.py`. `journeys.json` comes from `scripts/record_journeys.py`, and the page in `docs/assets/` embeds it. `search-activity.txt` is one retrieve call and `prompt-trace.txt` is one run per prompt, both shortened by hand.
