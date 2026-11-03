# Voltrieve: agentic RAG reference implementation on Azure

A clean-room reference implementation of agentic RAG on Azure, built around a fictional electric car maker, Voltrieve. It answers two questions with running code and visible logs: how client-side tools coexist with a Foundry-based agentic RAG solution, and why one would define and host an agent in Microsoft Foundry at all. It ships three runnable backends (a Foundry prompt agent, an own loop in the Web API, and a Foundry hosted agent), a CLI and a web client, and a synthetic document corpus generated from a single catalog file.

## Repository layout

| Path | Contents |
| --- | --- |
| `infra/` | Bicep modules and azd configuration |
| `search/` | JSON definitions and apply script for the AI Search objects |
| `data/` | Voltrieve source data file, document generator, generated docs |
| `services/dealer/` | The dealer web service |
| `api/` | The Web API, including the three backends |
| `agents/` | Prompt agent definitions and scripts; hosted agent packaging |
| `clients/cli/` | The CLI client |
| `clients/web/` | The SPA client |
| `docs/` | Runbook, comparison write-up, design |

## Status

Plan 1 (foundation) is in progress. Most directories above do not exist yet.
