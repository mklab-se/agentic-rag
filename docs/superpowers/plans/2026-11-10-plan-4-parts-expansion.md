# Spare Parts Expansion and Parts Stock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** About 300 to 400 new spare parts (tyres, interior controls, lighting, glass, wipers) with every existing article number unchanged, parts stock per dealer city, and a stock tool that names the closest dealer with stock on all three backends.

**Architecture:** The generator keeps deriving parts from templates in `parts.py`, now numbering added templates after all existing ones, and also writes the parts stock and dealer distances into the dealer service. The dealer service gets `GET /parts/stock`; `agent_core` gets one `check_part_stock` server tool that the own loop, the prompt agents (as a function tool) and the hosted agent all use.

**Tech Stack:** Python 3.12, pydantic, FastAPI (dealer), httpx, pytest, uv; Azure AI Search, Foundry agents, Container Apps (deploy only).

**Spec:** `docs/superpowers/specs/2026-11-10-parts-expansion-design.md`

## Global Constraints

- No em-dash (U+2014) anywhere: code, comments, docs, YAML, commit messages. Grep changed files for U+2014 before every commit.
- Every article number in today's catalog keeps its part key and fitting vehicles.
- Expected values in `tests/routing/questions.yaml` and `tests/grounding/questions.yaml` are derived from data at run time, never literals.
- A distance is always between two dealers, and only when the customer named a city. No delivery times, no invented stock.
- All three backends: own loop, prompt agent, hosted agent.
- No new Azure resources. Do not overwrite `docs/evidence/routing.json` or `routing.txt`: live routing runs use `--label`.
- Commit when a task says so; push only when the user asks.
- Distances (km, road): Stockholm-Uppsala 70, Stockholm-Göteborg 470, Stockholm-Malmö 615, Uppsala-Göteborg 455, Uppsala-Malmö 680, Göteborg-Malmö 270.

## Review Focus

1. A city the model spells differently ("Gothenburg", "goteborg") must not reach the dealer: the tool's `city` is an enum of the four exact names, and the dealer answers an unknown city with 422 naming the valid cities. Test in Tasks 5 and 6.
2. An article number that does not exist (a typo, or a number from another brand) gets "not a Voltrieve article number", never a stock figure. Test in Tasks 5 and 6.
3. The prompt agents and the hosted agent really get the new tool, not only the own loop. Both build their tools from `build_server_tools` (`agents/prompt/create_agents.py` `dealer_function_tools`, and the hosted agent's `agent_core`), so Task 6 tests `build_server_tools`; Task 8's live routing run proves each backend called it.
4. "My mirror is broken" without a side must get both sides, not a guess. Grounding question in Task 7.
5. A catalog change that is not followed by regenerating the stock file leaves stock for articles that no longer exist, or none for new ones. Freshness test in Task 4.

---

## Phase 1: the catalog

### Task 1: Append-only article numbers

**Files:**
- Modify: `data/generator/src/voltrieve_data/parts.py` (numbering, `DOCUMENTS`)
- Create: `data/generator/tests/fixtures/parts-index-2026-11-10.json` (a copy of today's `data/generated/parts-index.json`)
- Test: `data/generator/tests/test_parts.py`

**Interfaces:**
- Produces: `DOCUMENTS: dict[str, tuple[str, list[Template], list[Template]]]` (title, original templates, added templates). `build_parts` numbers every original template of every document first, in today's order, then every added template of every document, in document order then list order. New templates only ever go at the end of an added list.

- [ ] **Step 1:** Copy `data/generated/parts-index.json` to the fixture path. Write `test_existing_article_numbers_never_change`: for every part in the fixture, the part with the same article in `build_parts(catalog)` has the same `key` and the same `fits` names.
- [ ] **Step 2:** Add one throwaway template to the *original* list of the body document; run the test; expected FAIL (numbers shift). Remove it.
- [ ] **Step 3:** Change `DOCUMENTS` to three-tuples (added lists empty) and the numbering to originals first, then added. Update `parts_catalog.py` for the new tuple shape.
- [ ] **Step 4:** Add the same throwaway template to an *added* list; run; expected PASS; remove it. Full generator suite: PASS.
- [ ] **Step 5:** Commit: "Number new spare parts after the existing ones".

### Task 2: Wheels and tyres

**Files:**
- Modify: `data/generator/src/voltrieve_data/model.py` (`Wheel.tyre_size: str`), `data/voltrieve.yaml` (a tyre size per wheel), `data/generator/src/voltrieve_data/parts.py` (scope `wheel`, tyre templates, `Part.wheel`), `data/generator/src/voltrieve_data/parts_catalog.py` (index field `wheel`)
- Test: `data/generator/tests/test_parts.py`, `data/generator/tests/test_catalog.py`

**Interfaces:**
- Produces: `Scope` gains `"wheel"`: one article per model per wheel in `model.wheels`. Spec callables for wheel templates receive the `Wheel` (signature `(model: CarModel, wheel: Wheel) -> str`). `Part.wheel: str | None` (the wheel key). `parts-index.json` rows gain `"wheel"` (key or null).
- New document (added list, in `DOCUMENTS`): `"voltrieve-parts-wheels-tyres.md": ("Wheels and tyres", [], [...])` with templates `tyre_summer`, `tyre_winter_studless`, `tyre_winter_studded`, sold one per article (quantity 1). The spec names the size, the inches and wheel name, and the trims that have that wheel, for example `"Nordic studless winter tyre 245/45 R20, for the 20 inch Fern wheels (Fjord Plus and Prime)"`.

- [ ] **Step 1:** Tests: `test_every_wheel_has_a_tyre_size` (matches `^\d{3}/\d{2} R\d{2}$` and the R number equals `inches`); `test_each_wheel_gets_three_tyres` (for each model wheel, exactly one part per tyre key with `wheel == w.key`); `test_tyre_spec_names_size_and_trims` (spec contains `tyre_size` and every trim name that uses the wheel); `test_winter_wheel_sets_match_a_catalog_wheel` (each `VA-910x` accessory description names inches and a wheel name of a wheel of that model). Run: FAIL.
- [ ] **Step 2:** Add the field, sizes for all 10 wheels (realistic sizes, for example Spark 17 inch 205/55 R17, Atlas 22 inch 285/40 R22), the `wheel` scope and the templates. Fix any winter wheel set description that names a wheel the model does not have.
- [ ] **Step 3:** Run the generator suite: PASS, including Task 1's test. Commit: "Sell summer and winter tyres for every wheel".

### Task 3: Interior controls, lighting, glass, wipers and the words people use

**Files:**
- Modify: `data/generator/src/voltrieve_data/model.py` (`CarModel.drive_selector: Literal["stalk", "rotary"]`, `CarModel.rear_quarter_glass: bool`), `data/voltrieve.yaml`, `data/generator/src/voltrieve_data/parts.py`, `data/generator/src/voltrieve_data/parts_catalog.py` (catalog intro text)
- Test: `data/generator/tests/test_parts.py`

**Interfaces:**
- New document (added list): `"voltrieve-parts-interior.md": ("Interior and controls", [], [...])` with at least `drive_selector` (name "Drive selector stalk" or "Drive selector dial" per `drive_selector`), `indicator_stalk`, `wiper_stalk`, `window_switch_pack_driver`, window switches per other door, `hazard_switch`, `steering_buttons_left` and `_right`, `seat_switch_left` and `_right`.
- Added templates in existing documents: lighting (`indicator_front_left/right`, `side_repeater_left/right`, reversing and rear fog lamps), glass (`door_window` per corner, `rear_quarter_glass_left/right` when `rear_quarter_glass`, `panoramic_roof_glass` when any trim's `adds` contains "panoramic glass roof"), wipers and washers (`wiper_motor_front`, `wiper_motor_rear`, `washer_pump`, washer nozzles).
- Existing parts may get better text only (key, scope, `when` and fits unchanged): "wheel nut" in the wheel bolt set spec, "windshield" in the windscreen spec. New indicator specs include "blinker" and "direction light".

- [ ] **Step 1:** Tests: `test_catalog_has_between_750_and_830_parts`; `test_new_kinds_exist_for_every_model` (each listed key fits every model, except the conditional ones); `test_panoramic_roof_glass_only_where_a_trim_has_it`; `test_quarter_glass_follows_the_flag`; `test_everyday_words_are_searchable` (catalog text contains "wheel nut", "windshield", "blinker", "direction light"); `test_catalogs_say_there_is_no_engine_oil_and_no_gear_lever` (service items text says Voltrieve cars use no engine oil and the reduction gear oil is the only oil; interior text says the drive selector replaces a gear lever); `test_no_engine_oil_part` (no part name contains "engine oil"). Run: FAIL.
- [ ] **Step 2:** Implement. Tune the added kinds until the count is in range.
- [ ] **Step 3:** Run the generator suite: PASS, Task 1's test included. Regenerate (`uv run --project data/generator voltrieve-data generate`). Commit: "Add interior controls, lighting, glass and wiper parts".

## Phase 2: stock

### Task 4: Generated parts stock and distances

**Files:**
- Modify: `data/voltrieve.yaml` (`dealer_distances_km`, `parts_stock_pins`), `data/generator/src/voltrieve_data/model.py`, `data/generator/src/voltrieve_data/generate.py`
- Create: `data/generator/src/voltrieve_data/parts_stock.py`, `services/dealer/app/parts-stock.json` (generated)
- Test: `data/generator/tests/test_parts_stock.py`

**Interfaces:**
- Produces: `build_parts_stock(catalog: Catalog, parts: list[Part], cities: list[str]) -> dict` and `write_parts_stock(catalog: Catalog, path: Path) -> Path`. File shape: `{"cities": [...], "distances_km": {"Stockholm": {"Uppsala": 70, ...}, ...}, "stock": {"VP-10007": {"Stockholm": 3, ...}, ...}}`. Cities are read from `services/dealer/app/data.json`. `generate_all` writes it to `services/dealer/app/parts-stock.json`.
- Stock per article and city is deterministic: a stable hash (for example SHA-256 of `"<article>|<city>"`), mapped so that about a third of the values are 0. Pins override: `parts_stock_pins: [{key: door_mirror_right, model: spark, stock: {Stockholm: 0, Uppsala: 2, Göteborg: 1, Malmö: 0}}]`.

- [ ] **Step 1:** Tests: `test_stock_covers_every_article_and_city`; `test_stock_is_the_same_on_every_run`; `test_some_parts_are_out_everywhere` (at least 5); `test_some_parts_are_in_one_city_only` (at least 20); `test_most_parts_are_in_stock_somewhere` (at least 80 %); `test_spark_right_mirror_is_pinned`; `test_distances_are_symmetric_and_complete` (with the Global Constraints values); `test_committed_stock_file_is_current` (the committed file equals `build_parts_stock` output). Run: FAIL.
- [ ] **Step 2:** Implement; regenerate. Run: PASS. Commit: "Generate parts stock per dealer city".

### Task 5: Dealer endpoint

**Files:**
- Modify: `services/dealer/app/data.py`, `services/dealer/app/routes.py`, `services/dealer/app/main.py`
- Test: `services/dealer/tests/test_routes.py`

**Interfaces:**
- Produces: `PARTS_STOCK_PATH = Path(__file__).parent / "parts-stock.json"`; `DealerData.load(path, parts_path)`; `DealerData.part_stock(article: str, city: str | None) -> list[PartStockRow]` with `PartStockRow(city: str, in_stock: int, distance_km: int | None)`; `UnknownArticle(ValueError)`.
- `GET /parts/stock?article=VP-10007&city=Stockholm`, protected like `/stock`. Response `{"article": "VP-10007", "rows": [...]}`. With a city: that city first, then the others by distance from it, each with `distance_km` from the named city (null for the named city itself). Without a city: cities with stock first (most first), then the rest, `distance_km` null. Unknown article: 404 `"Unknown article: VP-..., not a Voltrieve article number"`. Unknown city: 422 naming the valid cities.

- [ ] **Step 1:** Tests: `test_part_stock_with_city_orders_by_distance`; `test_part_stock_without_city_has_no_distances`; `test_part_stock_unknown_article_is_404`; `test_part_stock_unknown_city_is_422_and_names_cities`; `test_part_stock_needs_auth`. Read expected values from the parts stock file in the tests. Run: FAIL.
- [ ] **Step 2:** Implement. Run the dealer suite: PASS. Commit: "Dealer service answers parts stock per city".

### Task 6: The stock tool on all three backends

**Files:**
- Modify: `agent_core/src/voltrieve_agent/dealer.py`, `agent_core/src/voltrieve_agent/server_tools.py`, `agent_core/src/voltrieve_agent/instructions.py`; if Task 2 or 3 added catalogs: `PARTS_DESCRIPTION` in `server_tools.py` and the descriptions in `search/definitions/07-parts-datasource.json`, `08-parts-index.json`, `11-parts-knowledge-source.json` and `12-parts-knowledge-base.json`
- Test: `agent_core/tests/test_server_tools.py`, `search/tests/test_definitions.py`

**Interfaces:**
- Consumes: Task 5's endpoint.
- Produces: `DealerClient.part_stock(article: str, city: str | None = None) -> str`; `ServerTool("check_part_stock", ...)` with schema `{"article": {"type": "string", "pattern": "^VP-\\d{5}$"}, "city": CITY_PROPERTY}`, `article` required, status `("checking_part_stock", "Checking parts stock")`. Description: check how many of a spare part are in stock at each dealer; find the article number with `search_spare_parts` first.
- Instructions (both `AGENT_INSTRUCTIONS` and `PROMPT_AGENT_INSTRUCTIONS`): for parts stock, find the article first, then call `check_part_stock` with the city the user named; answer per spec section 5 (number in the named city; otherwise the closest dealer with stock, its number and its distance from the named city, then the other dealers with stock; none anywhere: say so, no delivery time; no city named: the cities with stock, no distances). When the answer depends on a side, trim or drive the user did not give, give each option or ask. Change "They never help with a repair or a part" so it no longer forbids the parts stock tool.

- [ ] **Step 1:** Tests: `test_part_stock_tool_schema_and_description`; `test_part_stock_tool_calls_the_dealer` (fake dealer records the call); `test_instructions_explain_parts_stock_answers` (both instruction strings mention `check_part_stock` and "closest"); the parts descriptions test if catalogs were added. Run: FAIL.
- [ ] **Step 2:** Implement. Run the agent_core, api, agents/hosted and search suites: PASS. Commit: "Give every backend the parts stock tool".

## Phase 3: tests and the live run

### Task 7: Routing and grounding questions

**Files:**
- Modify: `tests/routing/check.py`, `tests/routing/questions.yaml`, `scripts/voltrieve_facts.py`, `tests/grounding/check.py`, `tests/grounding/questions.yaml`
- Test: `tests/contract/test_scripts.py`

**Interfaces:**
- Routing: a question may have `tools: [check_part_stock]`; `Run.tools` records every server tool called; `right` also needs every listed tool to have been called. The stock tool is not a source and not a search.
- Grounding: `{article}` and `{city}` in `ask` are filled from the facts at run time. New expectation types: `part_stock` (`model`, `key`, `city`, or `pick: out_everywhere`): the named city's number when it has stock; otherwise the closest city with stock, its number and its distance; none anywhere: declines and no number of pieces. `article` (`model`, `key`): the article number. `both_sides` (`model`, `key`): both side articles. `tyre` (`model`, `season`, optional `trim`): with a trim, that wheel's tyre size and one matching tyre article; without, every size of the model. `no_engine_oil` (`model`): declines and names no article except the reduction gear oil.
- Questions (both suites): the Spark right mirror in Stockholm; wiper blades for the Fjord; winter tyres for the Fjord Plus; winter tyres for the Fjord without a trim; "my Spark mirror is broken, which part do I need?" (both sides); a window switch for the Lumen; a front indicator for the Atlas; engine oil for the Ragn; a part out of stock everywhere (`pick: out_everywhere`).

- [ ] **Step 1:** Contract tests for each new fact type, with a right and a wrong answer each (values derived from the data files), and for the routing `tools` rule. Run: FAIL.
- [ ] **Step 2:** Implement; add the questions. Run the contract suite: PASS. Commit: "Routing and grounding questions for parts stock and the new parts".

### Task 8: Deploy and measure

- [ ] **Step 1:** Regenerate; `voltrieve-search upload --generated data/generated --dry-run` (expected: 0 stale, only new or changed blobs); upload; `voltrieve-search apply` if Task 6 changed definitions; `voltrieve-search index`; `voltrieve-search smoke` (expected 11/11).
- [ ] **Step 2:** `azd deploy dealer`, `azd deploy api`, `scripts/deploy-agents.sh`. Expected: the script's smoke check passes.
- [ ] **Step 3:** `uv run tests/grounding/check.py --save docs/evidence/grounding-parts.txt` on all three backends; `uv run tests/routing/check.py --repeats 2 --label parts-expansion-gpt-6.1-terra`. Fix document, description or instruction gaps until both pass.
- [ ] **Step 4:** Compare with `docs/evidence/models/descriptions-gpt-6.1-terra.json` (correctness, first text median, turns over 10 s, tokens); short section in `docs/model-comparison.md`; update the runbook where it lists the parts catalogs or dealer endpoints. Grep for U+2014. Commit.
