# Choosing a model

Which model should run the agent, and does it depend on the architecture? This page compares them on real runs of the 24 routing questions. Speed decides, as long as quality holds, and the limit we care about is **under 10 seconds to the first token**. Beyond that, users start to think the solution has stopped working.

## The result

The own loop runs `gpt-6.1-terra` by default, chosen from these results. The prompt agent, hosted agent and Search planning run `gpt-5.4-mini`.

| Architecture | Model | Median TTFT | Turns over 10 s | Two-base TTFT | Two-base total | USD per 1,000 turns |
| --- | --- | --- | --- | --- | --- | --- |
| **Own loop** | **`gpt-6.1-terra`** | **2.4 s** | **0 of 48** | **5.7 s** | **7.3 s** | 4.39 |
| Own loop | `gpt-6-luna` | 1.9 s | 2 of 48 | 7.3 s | 9.2 s | **1.83** |
| Own loop | `gpt-5.4-mini` | 2.1 s | 3 of 48 | 9.5 s | 11.0 s | 5.69 |
| Prompt agent | `gpt-6.1-terra` | 2.5 s | 5 of 48 | 10.7 s | 12.8 s | 7.24 |
| Prompt agent | `gpt-6-luna` | 2.2 s | 5 of 48 | 10.6 s | 12.3 s | 1.89 |
| Prompt agent | `gpt-5.4-mini` | 3.3 s | 9 of 48 | 14.7 s | 16.7 s | 8.05 |
| Hosted agent | `gpt-6.1-terra` | 7.3 s | 7 of 48 | 10.3 s | 11.9 s | 4.74 |
| Hosted agent | `gpt-6-luna` | 7.0 s | 8 of 48 | 10.9 s | 12.9 s | 1.77 |
| Hosted agent | `gpt-5.4-mini` | 7.2 s | 13 of 48 | 16.0 s | 17.4 s | 6.29 |

TTFT is time to first token, and total is time to last token. All nine combinations found 78 of 78 article numbers. All reached the right sources in every run, except one prompt agent run on `gpt-5.4-mini`.

- **Fastest:** the own loop with `gpt-6.1-terra`, the only combination that stayed under 10 seconds on every turn. Its slowest TTFT was 9.5 seconds.
- **Cheapest:** `gpt-6-luna`, at about a third of the cost of `gpt-5.4-mini`, and still a little faster than it.
- **The hosted agent** pays about 5 seconds on every turn for the hop into its session, whichever model it runs.
- **The prompt agent** had a few very slow turns, up to 84 seconds. These runs used all three backends at once, so a rate limit retry is a likely cause, but this wasn't confirmed.

## Waiting less painfully

The first `status` event reached the client in a median of 0.11 to 0.12 seconds on all three backends, with a slowest of 0.13 seconds over 12 runs each. So users see something happen right away, even on a turn that takes 10 seconds to start answering. It changes how the wait feels, not how long it is.

## Every agent model, on the own loop

48 runs each. Search planning stayed on `gpt-5.4-mini`.

| Model | Right sources | Articles | Simple question | Two bases | USD per 1,000 turns |
| --- | --- | --- | --- | --- | --- |
| `gpt-6.1-terra` | 48 of 48 | 78 of 78 | 1.7 s | 6.9 s | 4.71 |
| `gpt-5.6-terra` | 48 of 48 | 78 of 78 | 1.5 s | 7.2 s | 8.30 |
| `gpt-6-luna` | 48 of 48 | 78 of 78 | 1.4 s | 11.3 s | 1.68 |
| `gpt-5.4-mini` | 48 of 48 | 78 of 78 | 1.7 s | 12.2 s | 5.06 |
| `gpt-6.1-sol` | 48 of 48 | 78 of 78 | 2.0 s | 12.8 s | 7.42 |
| `gpt-5.4-nano` | 47 of 48 | 78 of 78 | 1.7 s | 21.4 s | 5.62 |

These times are to the last token. `gpt-5.4-nano` shows why token price alone can mislead: its tokens are cheap, but it made so many more calls that it cost more than `gpt-5.4-mini`.

## Search planning

Azure AI Search calls a model of its own to plan each search, so this is a separate choice.

| Planning model | Right sources | Articles | Two bases | USD per million, in / out |
| --- | --- | --- | --- | --- |
| `gpt-5.4-mini` | 20 of 20 | 78 of 78 | 10.9 s | 0.75 / 4.50 |
| `gpt-5.4-nano` | 20 of 20 | 78 of 78 | 12.5 s | 0.20 / 1.25 |
| `gpt-5.6-terra` | 20 of 20 | 78 of 78 | 10.2 s | 2.00 / 12.00 |
| `gpt-6-luna`, `gpt-6.1-terra` | Refused by Search | | | |

GPT-6 models are refused with `HTTP 400: Unsupported model type`, which matches Microsoft's list of supported models. The planning model made little difference, and the gaps here come from 8 runs, so they could be noise. So the agent and Search planning need separate deployments if the agent runs on GPT-6. That also stops them sharing a token limit.

## How the cost is estimated

Cost is the tokens each turn reported, at list price: Global Standard, Sweden Central, short context, read on 2026-11-05. It covers agent tokens, cached tokens, planning tokens and Search reasoning tokens at USD 0.022 per million.

- The prompt agent doesn't report planning tokens, so its searches use the own loop's average per search.
- It leaves out fixed costs, such as about USD 80 a month for Search Basic and the registry, and hosted agent session charges, so the hosted agent is cheaper here than it really is.
- Cache write charges are left out.
- The Search free monthly allowance isn't counted.

## How far to trust this

These are medians from 48 runs per combination, and only 8 of them per combination are two-base questions. Runs happened on one afternoon from one laptop. The Terra and Luna rows ran with the three backends at the same time, so rate limits may have touched some turns. The evidence is in [model-comparison.txt](evidence/model-comparison.txt), and the raw runs are in `docs/evidence/models/`.

To repeat it:

```sh
uv run scripts/compare_models.py gpt-5.4-mini gpt-6-luna
scripts/compare_architectures.sh gpt-6.1-terra gpt-6-luna gpt-5.4-mini
uv run scripts/model_costs.py
```
