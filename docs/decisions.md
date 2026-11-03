# Decisions

## Region

- Sweden Central hosts everything except Azure AI Search: Foundry, storage, Container Apps, registry and monitoring.
- Azure AI Search is placed in France Central through the `searchLocation` parameter (azd env value `AZURE_SEARCH_LOCATION`, default `francecentral`). Sweden Central and West Europe cannot currently create new search services, and France Central is the nearest EU region that can. Search reaches Foundry and storage over the public endpoints with Entra tokens, so the cross-region placement costs only a little latency.

## Search API version and the knowledge base model

- The search definitions use the GA REST API version 2026-04-01.
- The knowledge base is defined without a language model. Retrieval is semantic query to ranked chunks and references, with no LLM query planning.
- LLM query planning requires the 2026-08-01-preview API version and the Cognitive Services User role for the Search service identity on the Foundry account. Whether to move to the preview for plan 2 is an open decision for the user.

## No page or section field in the chunk index

The index has no page number or section field. The skillset splits extracted text into character-based chunks (with overlap), and the built-in extraction does not give a reliable source page or section for Markdown, DOCX and PDF alike, so a field would be wrong or empty for some formats. Citations use the document title and the chunk content instead.

## Dealer telemetry

OpenTelemetry for the dealer service moved to plan 2. In plan 1 the dealer logs structured JSON with a correlation id.

## Application Insights connection string

The Application Insights connection string passed to the dealer app is an ingestion identifier, not a secret: it only allows sending telemetry. It is therefore set as a plain environment value. Every other Azure call uses Entra tokens and no keys are stored anywhere.

## Facts still to record from Task 9

To be filled in after the first real `azd up`:

- Whether the role propagation retry in the post-provision hook was needed, and how long it waited.
- Indexer duration and the final item counts.
- Smoke test results and any reranker scores worth keeping as a baseline.
- The Foundry model deployment names and quota actually granted in Sweden Central.
- Anything in the search or Container Apps behaviour that differed from the plan.
