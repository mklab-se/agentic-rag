# Voltrieve Plan 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up everything the agent backends will sit on: the Voltrieve data and documents, the Azure AI Search pipeline from blob to knowledge base, the dealer service, the Azure infrastructure and the Entra app registrations, with a retrieval smoke test proving the knowledge base answers from our documents.

**Architecture:** Four independent Python projects (`data/generator`, `services/dealer`, `infra/scripts/entra`, `search`) plus Bicep under `infra/`, tied together by `azd` with a pre-provision hook (Entra) and a post-provision hook (upload, apply search objects, run indexer). Each project has its own `pyproject.toml`, tests and lock file so the dealer service can be containerised from its own folder. The Web API, clients and agent backends are plans 2 and 3; this plan leaves outputs (resource names, endpoints, client ids) in the `azd` environment for them.

**Tech Stack:** Python 3.12, `uv`, `pydantic` 2, `pyyaml`, `python-docx`, `fpdf2`, `pypdf` (tests), FastAPI, `uvicorn`, `PyJWT[crypto]`, `httpx`, `azure-identity`, `azure-storage-blob`, `pytest`, `respx` (httpx mocking), Bicep, Azure Developer CLI (`azd`), Azure CLI.

**Spec:** `docs/superpowers/specs/2026-11-03-voltrieve-agentic-rag-design.md`

## Global Constraints

- No em-dash (U+2014) anywhere: docs, code, comments, commit messages, generated documents. Grep before each commit with `git grep -nP '(*UTF)\x{2014}'`.
- No API keys, connection strings with keys, or secrets in source or in `azd` env values. Every Azure call uses Entra tokens (`DefaultAzureCredential` or `AzureCliCredential`).
- English only in documents and UI text.
- Python 3.12, `uv` for every Python project, dependencies pinned through `uv.lock`, committed.
- Region: Sweden Central, falling back to West Europe only if a required feature is missing; the choice and the reason go in `docs/decisions.md`.
- Azure AI Search REST api-version `2026-04-01` (GA). Any object that needs a preview version is recorded in `docs/decisions.md` with the feature that forced it.
- Role assignments by GUID, never by role name (Foundry roles were renamed).
- Low-cost SKUs: Search `basic`, Foundry `S0`, Container Apps consumption, ACR `Basic`, Static Web Apps `Free`.
- The five model names, segments and the figures in spec section 4.1 are fixed. Spark towing is `null` (not rated). Planted test cases in spec section 4.3 must hold.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. A v1 access token (`aud` = `api://<client-id>`) reaching the dealer service: it must be accepted alongside the v2 form (`aud` = client id GUID). Test added to Task 3.
2. A booking with a past date, an unknown model or an unknown city: 422 with a field-level message, never a 500 or a silent booking. Test added to Task 4.
3. An indexer run that finishes with per-document failures (an unsupported file in the container): the index command must exit non-zero and print the failing documents, not report success. Test added to Task 8.
4. A retrieve call returning HTTP 206 (a knowledge source failed): the result is marked partial and the activity errors are surfaced, not treated as an empty answer. Test added to Task 8.
5. The Entra setup run twice: no duplicate app registrations, roles or users; the second run is a no-op that still exports the same ids. Test added to Task 5.

---

### Task 1: Repository scaffold and the Voltrieve catalog

**Files:**
- Create: `README.md` (replace the one-line file), `.gitignore`, `.editorconfig`
- Create: `data/voltrieve.yaml`
- Create: `data/generator/pyproject.toml`, `data/generator/src/voltrieve_data/__init__.py`, `data/generator/src/voltrieve_data/model.py`, `data/generator/src/voltrieve_data/load.py`
- Test: `data/generator/tests/test_catalog.py`

**Interfaces:**
- Produces: `voltrieve_data.model.Catalog`, `CarModel`, `OptionPack`, `Market`, and `voltrieve_data.load.load_catalog(path: Path) -> Catalog`.

Catalog content (the single source of truth for every document):

```yaml
company:
  name: Voltrieve
  tagline: Electric cars that retrieve the joy of driving
markets:
  - { code: SE, currency: SEK }
  - { code: EU, currency: EUR }
awd_surcharge: { SE: 40000, EU: 3600 }
option_packs:
  Winter: { description: heat pump, heated steering wheel and rear seats, battery preconditioning, price: { SE: 18000, EU: 1600 } }
  Pilot Plus: { description: Voltrieve Pilot lane change assist and highway autopilot upgrade, price: { SE: 24000, EU: 2200 } }
  Tow: { description: electrically deployable tow bar and trailer stability control, price: { SE: 14000, EU: 1300 } }
  Sound: { description: 14 speaker Voltrieve Stage audio system, price: { SE: 12000, EU: 1100 } }
models:
  - name: Voltrieve Spark
    slug: spark
    segment: city car
    platform: V1
    voltage: 400
    battery_kwh: 42
    range_km: 310
    peak_charge_kw: 95
    towing_kg: null
    drive: [RWD]
    heat_pump_standard: false
    pilot_version: 2
    option_packs: [Winter, Sound]
    price: { SE: 289000, EU: 26500 }
    charging_curve: [[10, 95], [50, 80], [80, 40]]
    tagline: Small outside, generous inside
    highlights: [turning circle of 9.8 m, 2 ISOFIX seats, one pedal driving]
  - name: Voltrieve Lumen
    slug: lumen
    segment: hatchback
    platform: V1
    voltage: 400
    battery_kwh: 61
    range_km: 455
    peak_charge_kw: 135
    towing_kg: 750
    drive: [RWD, AWD]
    heat_pump_standard: true
    pilot_version: 2
    option_packs: [Winter, Pilot Plus, Sound]
    price: { SE: 379000, EU: 34500 }
    charging_curve: [[10, 135], [50, 110], [80, 55]]
    tagline: Light on its feet
    highlights: [frunk of 45 litres, 11 kW onboard charger, 360 camera]
  - name: Voltrieve Ragn
    slug: ragn
    segment: crossover
    platform: V2
    voltage: 800
    battery_kwh: 84
    range_km: 530
    peak_charge_kw: 240
    towing_kg: 1800
    drive: [AWD]
    heat_pump_standard: true
    pilot_version: 3
    option_packs: [Winter, Pilot Plus, Tow, Sound]
    price: { SE: 549000, EU: 49900 }
    charging_curve: [[10, 240], [50, 190], [80, 90]]
    tagline: Built for the long way round
    highlights: [ground clearance of 205 mm, off road mode, 22 kW onboard charger]
  - name: Voltrieve Fjord
    slug: fjord
    segment: estate
    platform: V2
    voltage: 800
    battery_kwh: 84
    range_km: 575
    peak_charge_kw: 240
    towing_kg: 2100
    drive: [RWD, AWD]
    heat_pump_standard: true
    pilot_version: 3
    option_packs: [Winter, Pilot Plus, Tow, Sound]
    price: { SE: 529000, EU: 47900 }
    charging_curve: [[10, 240], [50, 200], [80, 95]]
    tagline: Room for the whole weekend
    highlights: [boot of 640 litres, roof load of 100 kg, air suspension]
  - name: Voltrieve Atlas
    slug: atlas
    segment: large SUV
    platform: V2
    voltage: 800
    battery_kwh: 112
    range_km: 610
    peak_charge_kw: 320
    towing_kg: 2500
    drive: [AWD]
    heat_pump_standard: true
    pilot_version: 3
    option_packs: [Winter, Pilot Plus, Tow, Sound]
    price: { SE: 749000, EU: 67900 }
    charging_curve: [[10, 320], [50, 260], [80, 120]]
    tagline: Seven seats, zero compromise
    highlights: [seven seats, 3.5 kW vehicle to load outlet, rear wheel steering]
not_documented:
  - Euro NCAP
  - crash test
  - warranty
  - factory
  - production
```

Where AWD is optional, AWD adds the `awd_surcharge` to the list price. Pilot features: Pilot 2 = adaptive cruise, lane keeping; Pilot 3 = Pilot 2 plus traffic jam assist and automatic lane change (with Pilot Plus).

- [ ] **Step 1: Write the failing tests**

```python
# data/generator/tests/test_catalog.py
from pathlib import Path
from voltrieve_data.load import load_catalog

CATALOG = Path(__file__).parents[2] / "voltrieve.yaml"

def test_five_models_in_spec_order():
    cat = load_catalog(CATALOG)
    assert [m.slug for m in cat.models] == ["spark", "lumen", "ragn", "fjord", "atlas"]

def test_ragn_and_fjord_share_battery_but_differ_in_towing_and_range():
    cat = load_catalog(CATALOG)
    ragn, fjord = cat.by_slug("ragn"), cat.by_slug("fjord")
    assert ragn.battery_kwh == fjord.battery_kwh == 84
    assert fjord.towing_kg == 2100 and ragn.towing_kg == 1800
    assert fjord.range_km != ragn.range_km

def test_atlas_is_the_only_320kw_charger_and_largest_battery():
    cat = load_catalog(CATALOG)
    fastest = [m.slug for m in cat.models if m.peak_charge_kw == 320]
    assert fastest == ["atlas"]
    assert max(cat.models, key=lambda m: m.battery_kwh).slug == "atlas"

def test_spark_is_not_rated_for_towing_and_has_no_standard_heat_pump():
    spark = load_catalog(CATALOG).by_slug("spark")
    assert spark.towing_kg is None
    assert spark.heat_pump_standard is False

def test_every_model_has_a_price_in_every_market():
    cat = load_catalog(CATALOG)
    for m in cat.models:
        assert set(m.price) == {mk.code for mk in cat.markets}

def test_cheapest_awd_in_sweden_is_lumen():
    cat = load_catalog(CATALOG)
    awd = [m for m in cat.models if "AWD" in m.drive]
    assert min(awd, key=lambda m: cat.awd_price(m, "SE")).slug == "lumen"

def test_not_documented_terms_absent_from_catalog_text():
    cat = load_catalog(CATALOG)
    text = cat.all_text().lower()
    for term in cat.not_documented:
        assert term.lower() not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd data/generator && uv run pytest -q`
Expected: FAIL with `ModuleNotFoundError: voltrieve_data`

- [ ] **Step 3: Create the project and the models**

`data/generator/pyproject.toml`: name `voltrieve-data`, requires-python `>=3.12`, dependencies `pydantic>=2`, `pyyaml`, `python-docx`, `fpdf2`; dev `pytest`, `pypdf`; a script `voltrieve-data = "voltrieve_data.cli:main"` (cli arrives in Task 2).

`model.py`: pydantic models `Market(code: str, currency: str)`, `OptionPack(description: str, price: dict[str, int])`, `CarModel(name, slug, segment, platform: Literal["V1","V2"], voltage: int, battery_kwh: int, range_km: int, peak_charge_kw: int, towing_kg: int | None, drive: list[str], heat_pump_standard: bool, pilot_version: int, option_packs: list[str], price: dict[str, int], charging_curve: list[tuple[int, int]], tagline: str, highlights: list[str])`, `Company(name, tagline)`, `Catalog(company, markets, option_packs: dict[str, OptionPack], models: list[CarModel], awd_surcharge: dict[str, int], not_documented: list[str])` with methods `by_slug(slug) -> CarModel` (KeyError if missing), `awd_price(model, market) -> int` (base price plus surcharge when AWD is optional, base price when AWD is the only drive), `all_text() -> str` (every string field joined).

`load.py`: `load_catalog(path: Path) -> Catalog` reading YAML with `yaml.safe_load`.

Write `data/voltrieve.yaml` from the content above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd data/generator && uv run pytest -q`
Expected: 7 passed

- [ ] **Step 5: Scaffold the repository root**

`README.md`: title, one paragraph on what the project is, a repository layout table matching spec section 5.1, and a "Status" line saying plan 1 is in progress. `.gitignore`: Python (`.venv`, `__pycache__`, `.pytest_cache`), `node_modules`, `.azure/`, `*.env`, `.DS_Store`. `.editorconfig`: utf-8, lf, 2 spaces for yaml/json/bicep, 4 for python.

- [ ] **Step 6: Commit**

```bash
git add README.md .gitignore .editorconfig data/
git commit -m "Add Voltrieve catalog and data loader" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Document generator

**Files:**
- Create: `data/generator/src/voltrieve_data/brochure.py`, `spec_guide.py`, `buyers_guide.py`, `generate.py`, `cli.py`
- Create: `data/generated/` (committed output: 5 `.docx`, 5 `.pdf`, 1 `.md`, 1 `manifest.json`)
- Test: `data/generator/tests/test_documents.py`

**Interfaces:**
- Consumes: `Catalog`, `CarModel` from Task 1.
- Produces: `generate_all(catalog_path: Path, out_dir: Path) -> list[GeneratedDoc]` where `GeneratedDoc(path: Path, model_slug: str | None, doc_type: Literal["brochure","spec","guide"])`, and `manifest.json` in `out_dir` listing `[{file, model_slug, doc_type}]`. Task 8's uploader reads the manifest to set blob metadata.

File names: `voltrieve-<slug>-brochure.docx`, `voltrieve-<slug>-specifications.pdf`, `voltrieve-buyers-guide.md`.

- [ ] **Step 1: Write the failing tests**

```python
# data/generator/tests/test_documents.py
import json
from pathlib import Path
import docx, pypdf
from voltrieve_data.generate import generate_all
from voltrieve_data.load import load_catalog

CATALOG = Path(__file__).parents[2] / "voltrieve.yaml"
EM_DASH = chr(0x2014)

def docx_text(p): return "\n".join(par.text for par in docx.Document(p).paragraphs)
def pdf_text(p): return "\n".join(page.extract_text() for page in pypdf.PdfReader(p).pages)

def test_generates_eleven_documents_and_manifest(tmp_path):
    docs = generate_all(CATALOG, tmp_path)
    assert len(docs) == 11
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert {d["doc_type"] for d in manifest} == {"brochure", "spec", "guide"}

def test_spec_guide_has_exact_numbers(tmp_path):
    generate_all(CATALOG, tmp_path)
    text = pdf_text(tmp_path / "voltrieve-fjord-specifications.pdf")
    assert "2 100 kg" in text and "84 kWh" in text and "575 km" in text

def test_brochure_sells_without_towing_or_price_numbers(tmp_path):
    generate_all(CATALOG, tmp_path)
    text = docx_text(tmp_path / "voltrieve-fjord-brochure.docx")
    assert "Room for the whole weekend" in text
    assert "2 100 kg" not in text and "SEK" not in text

def test_spark_spec_says_not_rated_for_towing(tmp_path):
    generate_all(CATALOG, tmp_path)
    assert "not rated for towing" in pdf_text(tmp_path / "voltrieve-spark-specifications.pdf")

def test_prices_only_in_buyers_guide(tmp_path):
    generate_all(CATALOG, tmp_path)
    guide = (tmp_path / "voltrieve-buyers-guide.md").read_text()
    assert "749 000 SEK" in guide and "67 900 EUR" in guide
    for slug in ["spark", "lumen", "ragn", "fjord", "atlas"]:
        assert "SEK" not in pdf_text(tmp_path / f"voltrieve-{slug}-specifications.pdf")

def test_no_document_mentions_undocumented_topics(tmp_path):
    generate_all(CATALOG, tmp_path)
    cat = load_catalog(CATALOG)
    blobs = [docx_text(p) for p in tmp_path.glob("*.docx")] + \
            [pdf_text(p) for p in tmp_path.glob("*.pdf")] + \
            [(tmp_path / "voltrieve-buyers-guide.md").read_text()]
    for text in blobs:
        for term in cat.not_documented:
            assert term.lower() not in text.lower()

def test_no_em_dash_in_any_document(tmp_path):
    generate_all(CATALOG, tmp_path)
    texts = [docx_text(p) for p in tmp_path.glob("*.docx")] + \
            [pdf_text(p) for p in tmp_path.glob("*.pdf")] + \
            [p.read_text() for p in tmp_path.glob("*.md")]
    assert all(EM_DASH not in t for t in texts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd data/generator && uv run pytest tests/test_documents.py -q`
Expected: FAIL with `ModuleNotFoundError: voltrieve_data.generate`

- [ ] **Step 3: Implement the three writers**

Number formatting helper `fmt_int(n: int) -> str` using a normal space as thousands separator (`2 100`), used everywhere.

`brochure.py`: `write_brochure(model: CarModel, catalog: Catalog, out_dir: Path) -> Path` using python-docx. Sections: title (model name), tagline as subtitle, three short persuasive paragraphs built from `highlights`, segment and drive, a "Voltrieve Pilot" paragraph naming the Pilot version and its features, an "Option packs" list with descriptions (no prices), a closing line "Range up to <range_km> km (WLTP)". No towing figures, no prices, no charging numbers.

`spec_guide.py`: `write_spec_guide(model, catalog, out_dir) -> Path` using fpdf2 (built-in Helvetica, no external fonts). Sections with tables: Overview (segment, platform, system voltage); Battery and range (battery_kwh, range_km); Charging (peak_charge_kw, a three-row charging curve table "State of charge / Charge power", onboard charger from highlights where present); Towing ("Towing capacity: <n> kg (braked)" or the exact sentence "The Voltrieve Spark is not rated for towing."); Drive and chassis; Climate ("Heat pump: standard" or "Heat pump: available with the Winter pack"); Software (Pilot version and features); Option pack availability (names only).

`buyers_guide.py`: `write_buyers_guide(catalog, out_dir) -> Path` writing Markdown: a comparison table (battery, range, peak charge, towing, drive), a price table per market with the AWD surcharge row, option pack prices, and a "Which Voltrieve is for you" section with one paragraph per model.

`generate.py`: `GeneratedDoc` dataclass and `generate_all(catalog_path, out_dir) -> list[GeneratedDoc]` creating `out_dir`, calling the three writers, writing `manifest.json`.

`cli.py`: `main()` with argparse subcommand `generate --catalog data/voltrieve.yaml --out data/generated`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd data/generator && uv run pytest -q`
Expected: 14 passed

- [ ] **Step 5: Generate the committed documents**

Run: `cd data/generator && uv run voltrieve-data generate --catalog ../voltrieve.yaml --out ../generated && ls ../generated`
Expected: 11 documents plus `manifest.json`

- [ ] **Step 6: Commit**

```bash
git add data/
git commit -m "Generate Voltrieve brochures, specification guides and buyer's guide" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Dealer service token validation

**Files:**
- Create: `services/dealer/pyproject.toml`, `services/dealer/app/__init__.py`, `services/dealer/app/settings.py`, `services/dealer/app/auth.py`
- Test: `services/dealer/tests/conftest.py`, `services/dealer/tests/test_auth.py`

**Interfaces:**
- Produces: `app.auth.TokenValidator(tenant_id: str, client_id: str, required_role: str, jwks_fetcher: Callable[[], dict] | None = None)` with `async def validate(self, bearer: str) -> Claims`; `Claims(oid: str, app_id: str, roles: list[str])`; `app.auth.AuthError(status_code: int, detail: str)`; `app.settings.Settings(tenant_id, dealer_client_id, log_level)` from env `TENANT_ID`, `DEALER_CLIENT_ID`, `LOG_LEVEL`.

Validation rules: signature against JWKS from `https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys` (cached, refetched once on unknown `kid`), `iss` equals `https://login.microsoftonline.com/{tenant}/v2.0`, `aud` in `{client_id, f"api://{client_id}"}`, `exp`/`nbf` enforced, `roles` must contain `required_role`. Failures: missing or malformed header 401, bad signature or claims 401, missing role 403. Never log the token.

- [ ] **Step 1: Write the failing tests**

`conftest.py` generates an RSA key pair once per session, exposes fixtures `tenant_id`, `client_id`, `jwks` (a JWKS dict holding that key under `kid="test"`), `make_token(**overrides) -> str` (defaults: valid iss, aud = client id, roles `["Dealer.Access"]`, an `oid`, exp in 5 minutes; overrides `aud`, `roles`, `kid`, `exp_delta_seconds`), `validator` built with `jwks_fetcher=lambda: jwks`, `settings`, and `auth_header` (`{"Authorization": f"Bearer {make_token()}"}`).

```python
# services/dealer/tests/test_auth.py
import pytest
from app.auth import AuthError, TokenValidator

async def test_valid_v2_token(validator, make_token):
    claims = await validator.validate(make_token())
    assert "Dealer.Access" in claims.roles

async def test_v1_style_audience_accepted(validator, make_token, client_id):
    claims = await validator.validate(make_token(aud=f"api://{client_id}"))
    assert claims.oid

async def test_wrong_audience_rejected(validator, make_token):
    with pytest.raises(AuthError) as e:
        await validator.validate(make_token(aud="other"))
    assert e.value.status_code == 401

async def test_missing_role_is_403(validator, make_token):
    with pytest.raises(AuthError) as e:
        await validator.validate(make_token(roles=[]))
    assert e.value.status_code == 403

async def test_expired_token_rejected(validator, make_token):
    with pytest.raises(AuthError):
        await validator.validate(make_token(exp_delta_seconds=-60))

async def test_unknown_kid_triggers_one_refetch(make_token, jwks, client_id, tenant_id):
    calls = []
    def fetch():
        calls.append(1); return jwks
    v = TokenValidator(tenant_id, client_id, "Dealer.Access", jwks_fetcher=fetch)
    await v.validate(make_token())
    with pytest.raises(AuthError):
        await v.validate(make_token(kid="nope"))
    assert len(calls) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/dealer && uv run pytest tests/test_auth.py -q`
Expected: FAIL with `ModuleNotFoundError: app`

- [ ] **Step 3: Implement settings and the validator**

`pyproject.toml`: name `voltrieve-dealer`, dependencies `fastapi`, `uvicorn[standard]`, `PyJWT[crypto]`, `httpx`, `pydantic-settings`; dev `pytest`, `pytest-asyncio` (asyncio_mode auto), `respx`. Package dir `app`.

`auth.py`: implement `TokenValidator` as specified; use `jwt.PyJWKSet` / `jwt.decode` with `algorithms=["RS256"]`, `audience=[client_id, f"api://{client_id}"]`, `issuer=...`. Default `jwks_fetcher` does a blocking `httpx.get` wrapped in `asyncio.to_thread`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/dealer && uv run pytest tests/test_auth.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add services/dealer
git commit -m "Add dealer service token validation" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Dealer service endpoints, logging and container

**Files:**
- Create: `services/dealer/app/main.py`, `app/routes.py`, `app/data.py`, `app/data.json`, `app/logging_setup.py`, `services/dealer/Dockerfile`, `services/dealer/.dockerignore`
- Test: `services/dealer/tests/test_routes.py`, `data/generator/tests/test_dealer_prices_match_catalog.py`

**Interfaces:**
- Consumes: `TokenValidator`, `Settings` from Task 3.
- Produces: HTTP API consumed by plan 2's `check_stock`, `get_prices`, `book_test_drive` tools:
  - `GET /healthz` (no auth) returns `{"status":"ok"}`
  - `GET /stock?model=<slug>&city=<name>` returns `{"rows":[{"model":"atlas","city":"Göteborg","in_stock":3}]}`; `model` optional (all models), `city` optional (all cities).
  - `GET /prices?market=SE|EU` returns `{"market":"SE","currency":"SEK","prices":[{"model":"spark","list_price":289000}, ...]}`
  - `POST /test-drives` body `{"model","city","date":"YYYY-MM-DD","requester"}` returns 201 `{"booking_id": "<uuid>", ...echo}`; 422 on unknown model or city or a date not in the future.
  - Every response carries `X-Correlation-Id` (taken from the inbound header or generated).
- `app/main.py` exposes `create_app(settings: Settings, validator: TokenValidator | None = None) -> FastAPI`.

Data: `app/data.json` with cities `["Stockholm", "Göteborg", "Malmö", "Uppsala"]`, a stock matrix (integers 0 to 5, Atlas in Göteborg = 3, Spark in Uppsala = 0) and the price list copied from the catalog (same numbers as `data/voltrieve.yaml`).

- [ ] **Step 1: Write the failing tests**

```python
# services/dealer/tests/test_routes.py
import datetime as dt
from httpx import ASGITransport, AsyncClient
from app.main import create_app

def client(settings, validator):
    return AsyncClient(transport=ASGITransport(app=create_app(settings, validator)), base_url="http://t")

async def test_healthz_is_open(settings, validator):
    async with client(settings, validator) as c:
        assert (await c.get("/healthz")).status_code == 200

async def test_stock_requires_token(settings, validator):
    async with client(settings, validator) as c:
        assert (await c.get("/stock")).status_code == 401

async def test_stock_for_atlas_in_goteborg(settings, validator, auth_header):
    async with client(settings, validator) as c:
        r = await c.get("/stock", params={"model": "atlas", "city": "Göteborg"}, headers=auth_header)
    assert r.status_code == 200 and r.json()["rows"][0]["in_stock"] == 3

async def test_prices_in_eur(settings, validator, auth_header):
    async with client(settings, validator) as c:
        r = await c.get("/prices", params={"market": "EU"}, headers=auth_header)
    body = r.json()
    assert body["currency"] == "EUR"
    assert {"model": "atlas", "list_price": 67900} in body["prices"]

async def test_book_test_drive(settings, validator, auth_header):
    date = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    async with client(settings, validator) as c:
        r = await c.post("/test-drives", json={"model": "atlas", "city": "Göteborg", "date": date, "requester": "oid-1"}, headers=auth_header)
    assert r.status_code == 201 and r.json()["booking_id"]

async def test_booking_validation(settings, validator, auth_header):
    past = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    future = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    async with client(settings, validator) as c:
        for body in [
            {"model": "atlas", "city": "Göteborg", "date": past, "requester": "x"},
            {"model": "tesla", "city": "Göteborg", "date": future, "requester": "x"},
            {"model": "atlas", "city": "Oslo", "date": future, "requester": "x"},
        ]:
            r = await c.post("/test-drives", json=body, headers=auth_header)
            assert r.status_code == 422, body

async def test_correlation_id_echoed(settings, validator, auth_header):
    async with client(settings, validator) as c:
        r = await c.get("/stock", headers={**auth_header, "X-Correlation-Id": "abc-123"})
    assert r.headers["X-Correlation-Id"] == "abc-123"
```

```python
# data/generator/tests/test_dealer_prices_match_catalog.py
import json
from pathlib import Path
from voltrieve_data.load import load_catalog

ROOT = Path(__file__).parents[3]

def test_dealer_price_list_matches_catalog():
    cat = load_catalog(ROOT / "data" / "voltrieve.yaml")
    dealer = json.loads((ROOT / "services" / "dealer" / "app" / "data.json").read_text())
    for m in cat.models:
        for market, price in m.price.items():
            assert dealer["prices"][market][m.slug] == price
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/dealer && uv run pytest tests/test_routes.py -q` and `cd data/generator && uv run pytest tests/test_dealer_prices_match_catalog.py -q`
Expected: both FAIL (missing module / missing file)

- [ ] **Step 3: Implement data, routes, logging and app factory**

`data.py`: `DealerData.load(path) -> DealerData` with `stock(model: str | None, city: str | None) -> list[StockRow]`, `prices(market) -> PriceList`, `book(model, city, date, requester) -> Booking` raising `ValueError` subclasses mapped to 422 by the route. `data.json` layout: `{"cities": [...], "stock": {"<slug>": {"<city>": n}}, "prices": {"SE": {"<slug>": n}, "EU": {...}}, "currencies": {"SE": "SEK", "EU": "EUR"}}`.

`routes.py`: an APIRouter with a dependency `current_claims` that reads the `Authorization` header and calls `validator.validate`, converting `AuthError` to `HTTPException`. Pydantic request model for bookings with a `date` validator (`> today`).

`logging_setup.py`: `configure_logging(level)` emitting one JSON object per line to stdout with `time`, `level`, `logger`, `message`, `correlation_id`, `path`, `status`, `elapsed_ms`; a middleware in `main.py` sets a `contextvar` correlation id from `X-Correlation-Id` (or `uuid4`) and writes it to the response header. Log one line per request at INFO. Never log the Authorization header.

`main.py`: `create_app(settings, validator=None)` building the validator from settings when none is given; `app = create_app(Settings())` at module level for uvicorn.

`Dockerfile`: `python:3.12-slim`, install `uv`, `uv sync --frozen --no-dev`, non-root user `app`, `EXPOSE 8000`, `CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/dealer && uv run pytest -q` and `cd data/generator && uv run pytest -q`
Expected: 13 passed; 15 passed

- [ ] **Step 5: Build the container locally and hit healthz**

Run: `docker build -t voltrieve-dealer services/dealer && docker run --rm -d -p 8000:8000 -e TENANT_ID=t -e DEALER_CLIENT_ID=c --name d voltrieve-dealer && sleep 2 && curl -s localhost:8000/healthz; docker rm -f d`
Expected: `{"status":"ok"}`

- [ ] **Step 6: Commit**

```bash
git add services/dealer data/generator/tests/test_dealer_prices_match_catalog.py
git commit -m "Add dealer service endpoints, logging and container" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Entra setup script (pre-provision hook)

**Files:**
- Create: `infra/scripts/entra/pyproject.toml`, `infra/scripts/entra/src/voltrieve_entra/__init__.py`, `graph.py`, `apps.py`, `cli.py`
- Create: `hooks/preprovision.sh`
- Test: `infra/scripts/entra/tests/conftest.py`, `infra/scripts/entra/tests/test_apps.py`

**Interfaces:**
- Produces: `azd` env values `TENANT_ID`, `API_CLIENT_ID`, `API_SCOPE_ID`, `CLI_CLIENT_ID`, `WEB_CLIENT_ID`, `DEALER_CLIENT_ID`, `DEALER_APP_ROLE_ID`, `DEALER_SP_OBJECT_ID`, `API_SP_OBJECT_ID`, `CHAT_USER_ROLE_ID`, `TESTDRIVE_BOOK_ROLE_ID`, `TEST_USER_UPN`. Plan 2 reads these. The test user's password is printed once to the terminal and never stored.
- `voltrieve_entra.graph.GraphClient(token_provider: Callable[[], str])` with `get/post/patch(path, json=None) -> dict | None` against `https://graph.microsoft.com/v1.0`, raising `GraphError(status, body)`.
- `voltrieve_entra.apps`:
  - `ensure_application(g: GraphClient, display_name: str, desired: dict) -> dict` (find by `displayName`, create if missing, PATCH `desired` either way, return the application object)
  - `ensure_service_principal(g, app_id: str) -> dict`
  - `ensure_app_role_assignment(g, principal_object_id, resource_sp_object_id, app_role_id) -> dict` (no-op when it exists)
  - `ensure_oauth2_grant(g, client_sp_id, resource_sp_id, scope: str) -> dict`
  - `ensure_user(g, upn, display_name) -> tuple[dict, str | None]` (the generated password only when created)
  - `api_application_body(scope_id, chat_role_id, book_role_id) -> dict`, `cli_application_body(api_client_id, scope_id) -> dict`, `web_application_body(api_client_id, scope_id, redirect_uris: list[str]) -> dict`, `dealer_application_body(role_id) -> dict`
  - `setup(g, tenant_id, deployer_object_id, verified_domain, web_redirect_uris) -> dict[str, str]` returning the env values above.

Bodies follow the spec: API app `signInAudience: AzureADMyOrg`, `identifierUris: ["api://<appId>"]` (set after creation), `api.requestedAccessTokenVersion: 2`, scope `access_as_user` (type `User`), app roles `Chat.User` and `TestDrive.Book` (`allowedMemberTypes: ["User"]`). CLI app `isFallbackPublicClient: true`, `publicClient.redirectUris: ["http://localhost"]`, `requiredResourceAccess` for the scope. Web app `spa.redirectUris` = `["http://localhost:5173"]` plus any passed in. Dealer app `api.requestedAccessTokenVersion: 2`, app role `Dealer.Access` (`allowedMemberTypes: ["Application"]`), and `appRoleAssignmentRequired: true` on its service principal. Deployer gets `Chat.User` and `TestDrive.Book`; test user `voltrieve-tester@<verified_domain>` gets only `Chat.User`. Role and scope ids are stable UUIDs from `uuid5(NAMESPACE_URL, "voltrieve:<name>")` so reruns produce the same ids.

- [ ] **Step 1: Write the failing tests**

`conftest.py`: a `graph_mock` fixture (respx) that keeps in-memory stores for applications, service principals, users, app role assignments and oauth2 grants, answers `GET /applications?$filter=displayName eq '...'`, `POST /applications`, `PATCH /applications/{id}`, `GET /servicePrincipals?$filter=appId eq '...'`, `POST /servicePrincipals`, `PATCH /servicePrincipals/{id}`, `GET /servicePrincipals/{id}/appRoleAssignedTo`, `POST /servicePrincipals/{id}/appRoleAssignedTo`, `GET /users/{upn}`, `POST /users`, `GET /oauth2PermissionGrants`, `POST /oauth2PermissionGrants`; helpers `calls(method, path_prefix) -> int`, `user_id(upn) -> str`, `role_assignments_for(principal) -> set[str]`. A `graph` fixture returns `GraphClient(lambda: "tok")`.

```python
# infra/scripts/entra/tests/test_apps.py
from voltrieve_entra import apps

def test_api_body_has_scope_and_user_roles():
    body = apps.api_application_body("s", "c", "b")
    assert body["api"]["oauth2PermissionScopes"][0]["value"] == "access_as_user"
    assert {r["value"] for r in body["appRoles"]} == {"Chat.User", "TestDrive.Book"}
    assert all(r["allowedMemberTypes"] == ["User"] for r in body["appRoles"])

def test_dealer_body_has_application_role_and_v2_tokens():
    body = apps.dealer_application_body("r")
    assert body["appRoles"][0]["allowedMemberTypes"] == ["Application"]
    assert body["api"]["requestedAccessTokenVersion"] == 2

def test_ensure_application_creates_when_missing(graph_mock, graph):
    app = apps.ensure_application(graph, "voltrieve-api", {"signInAudience": "AzureADMyOrg"})
    assert graph_mock.calls("POST", "/applications") == 1 and app["appId"]

def test_ensure_application_is_idempotent(graph_mock, graph):
    apps.ensure_application(graph, "voltrieve-api", {})
    apps.ensure_application(graph, "voltrieve-api", {})
    assert graph_mock.calls("POST", "/applications") == 1
    assert graph_mock.calls("PATCH", "/applications") == 2

def test_setup_twice_yields_same_ids_and_no_duplicates(graph_mock, graph):
    first = apps.setup(graph, "tid", "deployer-oid", "contoso.onmicrosoft.com", [])
    second = apps.setup(graph, "tid", "deployer-oid", "contoso.onmicrosoft.com", [])
    assert first == second
    assert graph_mock.calls("POST", "/applications") == 4
    assert graph_mock.calls("POST", "/users") == 1

def test_test_user_gets_only_chat_role(graph_mock, graph):
    env = apps.setup(graph, "tid", "deployer-oid", "contoso.onmicrosoft.com", [])
    roles = graph_mock.role_assignments_for(principal=graph_mock.user_id(env["TEST_USER_UPN"]))
    assert roles == {env["CHAT_USER_ROLE_ID"]}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd infra/scripts/entra && uv run pytest -q`
Expected: FAIL with `ModuleNotFoundError: voltrieve_entra`

- [ ] **Step 3: Implement the Graph client, app bodies and setup**

`pyproject.toml`: name `voltrieve-entra`, dependencies `httpx`, `azure-identity`; dev `pytest`, `respx`; script `voltrieve-entra = "voltrieve_entra.cli:main"`.

`graph.py`: `GraphClient` as specified; 204 returns `None`.

`apps.py`: functions as in the Interfaces block. `ensure_application` PATCHes `identifierUris` for the API app after the `appId` is known. Passwords from `secrets.token_urlsafe(24)`; `passwordProfile.forceChangePasswordNextSignIn: false`.

`cli.py`: `main()` with subcommands:
- `setup` (args `--verified-domain`, `--web-redirect-uri` repeatable): token from `AzureCliCredential().get_token("https://graph.microsoft.com/.default")`, deployer object id from `GET /me`, runs `setup`, then `azd env set KEY VALUE` for each returned pair via `subprocess.run`, and prints the test user password once with a warning.
- `assign-app-role` (args `--principal-object-id`, `--resource-sp-object-id`, `--app-role-id`): calls `ensure_app_role_assignment`; used by plan 2's post-provision for the Web API identity.

`hooks/preprovision.sh`:

```sh
#!/bin/sh
set -eu
DOMAIN="${VOLTRIEVE_VERIFIED_DOMAIN:-$(az rest -m GET -u 'https://graph.microsoft.com/v1.0/domains' --query "value[?isDefault].id | [0]" -o tsv)}"
uv run --project infra/scripts/entra voltrieve-entra setup --verified-domain "$DOMAIN"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd infra/scripts/entra && uv run pytest -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add infra/scripts/entra hooks/preprovision.sh
git commit -m "Add Entra app registration setup script" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Azure infrastructure with Bicep and azd

**Files:**
- Create: `azure.yaml`, `infra/main.bicep`, `infra/main.parameters.json`
- Create: `infra/modules/monitoring.bicep`, `foundry.bicep`, `search.bicep`, `storage.bicep`, `registry.bicep`, `containerapps-env.bicep`, `dealer-app.bicep`, `role.bicep`
- Create: `hooks/postprovision.sh` (skeleton; Task 8 fills it), `docs/decisions.md` (started)
- Test: `infra/tests/test_bicep.sh`

**Interfaces:**
- Consumes: env values from Task 5 (`TENANT_ID`, `DEALER_CLIENT_ID`).
- Produces: Bicep outputs written to the `azd` env: `AZURE_RESOURCE_GROUP`, `AZURE_LOCATION`, `FOUNDRY_ACCOUNT_NAME`, `FOUNDRY_ENDPOINT` (`https://<account>.services.ai.azure.com`), `FOUNDRY_PROJECT_ENDPOINT` (`https://<account>.services.ai.azure.com/api/projects/<project>`), `CHAT_DEPLOYMENT`, `EMBEDDING_DEPLOYMENT`, `EMBEDDING_MODEL`, `SEARCH_ENDPOINT`, `SEARCH_SERVICE_NAME`, `STORAGE_ACCOUNT_NAME`, `STORAGE_RESOURCE_ID`, `DOCS_CONTAINER` (`voltrieve-docs`), `AZURE_CONTAINER_REGISTRY_ENDPOINT`, `AZURE_CONTAINER_REGISTRY_NAME`, `CONTAINER_APPS_ENVIRONMENT_ID`, `APPLICATIONINSIGHTS_CONNECTION_STRING`, `DEALER_URL`, `DEALER_PRINCIPAL_ID`.
- `role.bicep` module: params `principalId`, `roleDefinitionId` (GUID), `principalType` ('ServicePrincipal' | 'User'); the caller sets `scope:`. Plan 2 reuses it.

Resource decisions:

- `main.bicep` `targetScope = 'subscription'`, creates `rg-voltrieve-<env>`; params `environmentName`, `location` (default `swedencentral`), `principalId` (deployer, from `AZURE_PRINCIPAL_ID`), `tenantId`, `dealerClientId`, `chatModelName` (default `gpt-5.4-mini`), `chatModelVersion` (default `2026-03-17`), `embeddingModelName` (default `text-embedding-3-large`), `embeddingModelVersion` (default `1`).
- `monitoring.bicep`: Log Analytics (`PerGB2018`, 30 days) and workspace-based Application Insights.
- `foundry.bicep`: `Microsoft.CognitiveServices/accounts@2025-06-01` kind `AIServices`, `allowProjectManagement: true`, `customSubDomainName`, `disableLocalAuth: true`, system identity; child project; two deployments (`GlobalStandard`, capacity 10 each) chained with `dependsOn`; project connection to App Insights per the Foundry samples (`category: 'AppInsights'`, `authType: 'ApiKey'`, `credentials.key` = connection string, `isSharedToAll: true`, api-version `2025-04-01-preview`) with the comment `The App Insights connection string is an ingestion endpoint identifier, not a secret`.
- `search.bicep`: `Microsoft.Search/searchServices@2025-05-01`, sku `basic`, `semanticSearch: 'standard'`, `disableLocalAuth: true`, system identity, 1 replica, 1 partition.
- `storage.bicep`: StorageV2, `allowBlobPublicAccess: false`, `allowSharedKeyAccess: false`, `minimumTlsVersion: 'TLS1_2'`, blob container `voltrieve-docs`.
- `registry.bicep`: ACR `Basic`, admin user disabled.
- `containerapps-env.bicep`: managed environment bound to Log Analytics; the `listKeys()` for the workspace ingestion key carries the comment `Log Analytics ingestion key for the Container Apps environment; not an application secret`.
- `dealer-app.bicep`: Container App `ca-dealer-<env>`, system identity, external ingress on 8000, `registries: [{ server, identity: 'system' }]`, env `TENANT_ID`, `DEALER_CLIENT_ID`, `APPLICATIONINSIGHTS_CONNECTION_STRING`, `LOG_LEVEL=INFO`; initial image `mcr.microsoft.com/k8se/quickstart:latest` and tag `azd-service-name: dealer` so `azd deploy` swaps the image; scale 0 to 2, 0.5 vCPU, 1 GiB. The AcrPull assignment is declared in the same module and the app `dependsOn` it.
- Role assignments (GUIDs):
  - Search identity on Storage: Storage Blob Data Reader `2a2b9908-6ea1-4ae2-8e65-a410df84e7d1`
  - Search identity on the Foundry account: Cognitive Services OpenAI User `5e0bd9bd-7b93-4f28-af87-19fc36ad61bd`
  - Deployer on Search: Search Service Contributor `7ca78c08-252a-4471-8644-bb5ff32d4ba0`, Search Index Data Contributor `8ebe5a00-799e-43f5-93ac-243d3dce84a7`
  - Deployer on Storage: Storage Blob Data Contributor `ba92f5b4-2d11-453d-a403-e96b0029c9fe`
  - Deployer on the Foundry account: Foundry User `53ca6127-db72-4b80-b1b0-d745d6d5456d`
  - Dealer app identity on ACR: AcrPull `7f951dda-4ed3-4680-a7ca-43fe172d538d`
- `azure.yaml`: name `voltrieve`; service `dealer` (`project: ./services/dealer`, `language: python`, `host: containerapp`, `docker.remoteBuild: true`); hooks `preprovision` and `postprovision` (posix `sh`, `interactive: true` for preprovision). Plan 2 adds `api` and `web`.
- `main.parameters.json` maps `${AZURE_ENV_NAME}`, `${AZURE_LOCATION}`, `${AZURE_PRINCIPAL_ID}`, `${TENANT_ID}`, `${DEALER_CLIENT_ID}`.

- [ ] **Step 1: Write the failing test script**

```sh
# infra/tests/test_bicep.sh
#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
az bicep build --file main.bicep --stdout > /dev/null
az bicep lint --file main.bicep
# every role assignment uses a GUID, never a role name
if grep -rn "roleDefinitionId.*'[A-Z][a-zA-Z ]*'" modules/ main.bicep; then echo "role name used"; exit 1; fi
# the only key lookup allowed is the commented Log Analytics ingestion key
if grep -rn -i "listKeys\|apiKey\|accountKey" modules/ main.bicep | grep -v "not an application secret"; then echo "key usage found"; exit 1; fi
echo "bicep ok"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `sh infra/tests/test_bicep.sh`
Expected: FAIL, `main.bicep` not found

- [ ] **Step 3: Write the Bicep files, `azure.yaml`, parameters and the hook skeleton**

Follow the decisions above. `hooks/postprovision.sh` for now: `#!/bin/sh`, `set -eu`, `echo "postprovision: nothing yet"`. Start `docs/decisions.md` with a heading and an empty "Region" entry.

- [ ] **Step 4: Run the test script to verify it passes**

Run: `sh infra/tests/test_bicep.sh`
Expected: `bicep ok`, no lint warnings

- [ ] **Step 5: Preview against the subscription**

Run: `azd env new voltrieve-dev --location swedencentral --subscription <id>` (once), then `azd provision --preview`
Expected: a plan listing the resource group and every resource above, no errors. If a model version is rejected, run `az cognitiveservices model list --location swedencentral -o table | grep -E "gpt-5|text-embedding"` and update the defaults; record the chosen names in `docs/decisions.md`.

- [ ] **Step 6: Commit**

```bash
git add azure.yaml infra hooks/postprovision.sh docs/decisions.md
git commit -m "Add Bicep infrastructure and azd configuration" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Azure AI Search definitions and apply tool

**Files:**
- Create: `search/pyproject.toml`, `search/src/voltrieve_search/__init__.py`, `client.py`, `definitions.py`, `cli.py`
- Create: `search/definitions/01-datasource.json`, `02-index.json`, `03-skillset.json`, `04-indexer.json`, `05-knowledge-source.json`, `06-knowledge-base.json`
- Test: `search/tests/conftest.py`, `search/tests/test_definitions.py`, `search/tests/test_client.py`

**Interfaces:**
- Produces:
  - `voltrieve_search.client.SearchRestClient(endpoint: str, token_provider: Callable[[], str], api_version: str = "2026-04-01")` with `put(path: str, body: dict) -> dict`, `post(path, body=None) -> tuple[int, dict]`, `get(path) -> dict`, raising `SearchApiError(status, message)` on 4xx/5xx.
  - `voltrieve_search.definitions.render(template_text: str, values: dict[str, str]) -> dict` replacing `{{KEY}}` placeholders, raising `KeyError` on any left unreplaced.
  - `voltrieve_search.definitions.DEFINITION_ORDER = ["datasources", "indexes", "skillsets", "indexers", "knowledgesources", "knowledgebases"]` and `apply_all(client, values, definitions_dir: Path) -> list[str]` applying the six files in filename order with `PUT /{collection}/{body["name"]}`.
  - Object names: `voltrieve-docs-ds`, `voltrieve-docs-index`, `voltrieve-docs-skillset`, `voltrieve-docs-indexer`, `voltrieve-docs-ks`, `voltrieve-kb`. Plans 2 and 3 use `voltrieve-kb` and the MCP URL `{SEARCH_ENDPOINT}/knowledgebases/voltrieve-kb/mcp?api-version=2026-04-01`.
  - Placeholders: `{{STORAGE_RESOURCE_ID}}`, `{{DOCS_CONTAINER}}`, `{{FOUNDRY_ENDPOINT}}`, `{{EMBEDDING_DEPLOYMENT}}`, `{{EMBEDDING_MODEL}}`.

Definition content (api-version 2026-04-01):

`01-datasource.json`: `type: azureblob`, `credentials.connectionString: "ResourceId={{STORAGE_RESOURCE_ID}};"`, `container.name: "{{DOCS_CONTAINER}}"`.

`02-index.json` fields: `chunk_id` (key, `Edm.String`, `analyzer: keyword`, filterable, sortable), `parent_id` (filterable), `title` (searchable, filterable, retrievable), `chunk` (searchable, retrievable), `text_vector` (`Collection(Edm.Single)`, searchable, `retrievable: false`, `stored: false`, `dimensions: 3072`, `vectorSearchProfile: hnsw-profile`), `source_path` (filterable, retrievable), `model_slug` (filterable, facetable, retrievable), `doc_type` (filterable, facetable, retrievable). `vectorSearch`: algorithm `hnsw-alg` (cosine, m 4, efConstruction 400, efSearch 500), profile `hnsw-profile` with vectorizer `aoai-vectorizer` (`kind: azureOpenAI`, `azureOpenAIParameters`: `resourceUri: "{{FOUNDRY_ENDPOINT}}"`, `deploymentId: "{{EMBEDDING_DEPLOYMENT}}"`, `modelName: "{{EMBEDDING_MODEL}}"`, no apiKey, no authIdentity). `semantic.defaultConfiguration: semantic-config`, title field `title`, content field `chunk`. `description`: "Voltrieve electric car brochures, technical specification guides and the buyer's guide."

`03-skillset.json`: SplitSkill (`context /document`, `textSplitMode pages`, `maximumPageLength 2000`, `pageOverlapLength 500`, `unit characters`, input `text` from `/document/content`, output `textItems` as `pages`); AzureOpenAIEmbeddingSkill (`context /document/pages/*`, same resource placeholders, `dimensions 3072`, input `text` from `/document/pages/*`, output `embedding` as `text_vector`); `indexProjections.selectors[0]`: `targetIndexName voltrieve-docs-index`, `parentKeyFieldName parent_id`, `sourceContext /document/pages/*`, mappings `chunk` from `/document/pages/*`, `text_vector` from `/document/pages/*/text_vector`, `title` from `/document/metadata_storage_name`, `source_path` from `/document/metadata_storage_path`, `model_slug` from `/document/model_slug`, `doc_type` from `/document/doc_type`; `parameters.projectionMode: skipIndexingParentDocuments`. Do not map `chunk_id` or `parent_id`.

`04-indexer.json`: binds the three, no schedule, `parameters.configuration`: `dataToExtract contentAndMetadata`, `parsingMode default`, `indexedFileNameExtensions ".pdf,.docx,.md"`, `failOnUnsupportedContentType false`, `failOnUnprocessableDocument false`.

`05-knowledge-source.json`: `kind searchIndex`, `searchIndexParameters`: `searchIndexName voltrieve-docs-index`, `semanticConfigurationName semantic-config`, `sourceDataFields` `[chunk_id, title, chunk, source_path, model_slug, doc_type]` (as `[{"name": ...}]`), `searchFields` `[chunk, title]`, `description` as for the index.

`06-knowledge-base.json`: `knowledgeSources: [{name: voltrieve-docs-ks}]`, `description`, no `models`.

- [ ] **Step 1: Write the failing tests**

`conftest.py`: `fake_client` fixture, an object with `puts: list[tuple[str, dict]]` and `put(path, body)` appending and returning `body`.

```python
# search/tests/test_definitions.py
import json
from pathlib import Path
import pytest
from voltrieve_search.definitions import render, apply_all, DEFINITION_ORDER

DEFS = Path(__file__).parents[1] / "definitions"
VALUES = {"STORAGE_RESOURCE_ID": "/subscriptions/s/rg/x", "DOCS_CONTAINER": "voltrieve-docs",
          "FOUNDRY_ENDPOINT": "https://f.services.ai.azure.com", "EMBEDDING_DEPLOYMENT": "emb", "EMBEDDING_MODEL": "text-embedding-3-large"}

def test_render_replaces_all_placeholders():
    out = render((DEFS / "01-datasource.json").read_text(), VALUES)
    assert out["credentials"]["connectionString"] == "ResourceId=/subscriptions/s/rg/x;"

def test_render_fails_on_unreplaced_placeholder():
    with pytest.raises(KeyError):
        render('{"a": "{{MISSING}}"}', {})

def test_all_definitions_render_and_contain_no_keys():
    for f in sorted(DEFS.glob("*.json")):
        body = render(f.read_text(), VALUES)
        assert "apiKey" not in json.dumps(body) and "api-key" not in json.dumps(body)

def test_index_meets_knowledge_source_requirements():
    idx = render((DEFS / "02-index.json").read_text(), VALUES)
    key = next(f for f in idx["fields"] if f.get("key"))
    assert key["analyzer"] == "keyword"
    assert idx["semantic"]["defaultConfiguration"] == "semantic-config"
    vec = next(f for f in idx["fields"] if f["name"] == "text_vector")
    assert vec["dimensions"] == 3072 and vec["stored"] is False

def test_skillset_projections_do_not_map_key_fields():
    ss = render((DEFS / "03-skillset.json").read_text(), VALUES)
    names = {m["name"] for m in ss["indexProjections"]["selectors"][0]["mappings"]}
    assert "chunk_id" not in names and "parent_id" not in names
    assert {"model_slug", "doc_type", "chunk", "text_vector"} <= names

def test_apply_all_puts_in_order(fake_client):
    applied = apply_all(fake_client, VALUES, DEFS)
    assert applied == ["voltrieve-docs-ds", "voltrieve-docs-index", "voltrieve-docs-skillset",
                       "voltrieve-docs-indexer", "voltrieve-docs-ks", "voltrieve-kb"]
    assert [p.split("/")[1] for p, _ in fake_client.puts] == DEFINITION_ORDER
```

```python
# search/tests/test_client.py
import respx, httpx, pytest
from voltrieve_search.client import SearchRestClient, SearchApiError

@respx.mock
def test_put_sends_bearer_and_api_version():
    route = respx.put("https://s.search.windows.net/indexes/i?api-version=2026-04-01").mock(return_value=httpx.Response(201, json={"name": "i"}))
    c = SearchRestClient("https://s.search.windows.net", lambda: "tok")
    assert c.put("/indexes/i", {"name": "i"}) == {"name": "i"}
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"

@respx.mock
def test_error_raises_with_message():
    respx.put("https://s.search.windows.net/indexes/i?api-version=2026-04-01").mock(return_value=httpx.Response(400, json={"error": {"message": "bad field"}}))
    c = SearchRestClient("https://s.search.windows.net", lambda: "tok")
    with pytest.raises(SearchApiError) as e:
        c.put("/indexes/i", {})
    assert "bad field" in str(e.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd search && uv run pytest -q`
Expected: FAIL with `ModuleNotFoundError: voltrieve_search`

- [ ] **Step 3: Implement client, definitions module, and the six JSON files**

`pyproject.toml`: name `voltrieve-search`, dependencies `httpx`, `azure-identity`, `azure-storage-blob`; dev `pytest`, `respx`; script `voltrieve-search = "voltrieve_search.cli:main"`.

`definitions.py`: the `0N-` file prefix maps to `DEFINITION_ORDER[N-1]`.

`cli.py`: `main()` with subcommand `apply` reading values from env (`STORAGE_RESOURCE_ID`, `DOCS_CONTAINER`, `FOUNDRY_ENDPOINT`, `EMBEDDING_DEPLOYMENT`, `EMBEDDING_MODEL`, `SEARCH_ENDPOINT`) and a token provider from `DefaultAzureCredential().get_token("https://search.azure.com/.default")`. Task 8 adds more subcommands.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd search && uv run pytest -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add search
git commit -m "Add Azure AI Search definitions and apply tool" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Upload, index, retrieve and smoke test

**Files:**
- Create: `search/src/voltrieve_search/upload.py`, `indexer.py`, `retrieve.py`, `smoke.py`, `search/smoke-questions.json`
- Modify: `search/src/voltrieve_search/cli.py`, `hooks/postprovision.sh`
- Test: `search/tests/test_indexer.py`, `search/tests/test_retrieve.py`, `search/tests/test_smoke.py`

**Interfaces:**
- Produces:
  - `upload.upload_documents(account_url: str, container: str, generated_dir: Path, credential) -> int` uploading every file in `manifest.json` with blob metadata `model_slug` (empty string when none) and `doc_type`, overwriting; returns the count.
  - `indexer.run_and_wait(client, name: str, timeout_s: int = 600, poll_s: int = 10) -> IndexerRun` where `IndexerRun(status: str, items_processed: int, items_failed: int, errors: list[str])`; raises `IndexerFailed(run)` when `items_failed > 0`, when status is not `success`, or on timeout (status `timeout`).
  - `retrieve.retrieve(client, kb_name: str, question: str, max_output_tokens: int = 5000) -> RetrieveResult` with `RetrieveResult(chunks: list[Chunk], references: list[Reference], activity: list[dict], partial: bool)`, `Chunk(ref_id: str, title: str, content: str)`, `Reference(id: str, doc_key: str, reranker_score: float | None, source_data: dict | None)`. Request body: `{"intents":[{"type":"semantic","search":question}], "knowledgeSourceParams":[{"kind":"searchIndex","knowledgeSourceName":"voltrieve-docs-ks","includeReferences":true,"includeReferenceSourceData":true}], "maxOutputSizeInTokens":max_output_tokens, "includeActivity":true}` posted to `/knowledgebases/{kb_name}/retrieve`. HTTP 206 sets `partial=True`. Plan 2's `search_voltrieve_docs` tool wraps this function.
  - `smoke.run_smoke(client, kb_name, questions: list[SmokeQuestion]) -> list[SmokeOutcome]`, `SmokeQuestion(question, expect_title_contains: str, expect_doc_type: str)`, `SmokeOutcome(question, passed: bool, top_titles: list[str])`.

`search/smoke-questions.json`:

```json
[
  {"question": "What is the towing capacity of the Voltrieve Fjord?", "expect_title_contains": "fjord-specifications", "expect_doc_type": "spec"},
  {"question": "How fast can the Voltrieve Atlas charge?", "expect_title_contains": "atlas-specifications", "expect_doc_type": "spec"},
  {"question": "Can the Voltrieve Spark tow a trailer?", "expect_title_contains": "spark-specifications", "expect_doc_type": "spec"},
  {"question": "What does the Voltrieve Atlas cost in Sweden?", "expect_title_contains": "buyers-guide", "expect_doc_type": "guide"},
  {"question": "Why would I enjoy driving a Voltrieve Lumen?", "expect_title_contains": "lumen-brochure", "expect_doc_type": "brochure"}
]
```

A question passes when any of the top five references has `source_data.title` containing `expect_title_contains` and `source_data.doc_type == expect_doc_type`.

- [ ] **Step 1: Write the failing tests**

```python
# search/tests/test_indexer.py
import pytest
from voltrieve_search.indexer import run_and_wait, IndexerFailed

class Client:
    def __init__(self, statuses): self.statuses = list(statuses); self.posted = []
    def post(self, path, body=None): self.posted.append(path); return 202, {}
    def get(self, path): return self.statuses.pop(0)

def status(s, failed=0, errors=()):
    return {"lastResult": {"status": s, "itemsProcessed": 11, "itemsFailed": failed,
            "errors": [{"key": k, "errorMessage": "unsupported"} for k in errors]}}

def test_success_after_polling():
    c = Client([{"lastResult": None}, status("inProgress"), status("success")])
    run = run_and_wait(c, "voltrieve-docs-indexer", timeout_s=5, poll_s=0)
    assert run.status == "success" and c.posted == ["/indexers/voltrieve-docs-indexer/run"]

def test_per_document_failures_raise_with_keys():
    c = Client([status("success", failed=1, errors=["bad.xyz"])])
    with pytest.raises(IndexerFailed) as e:
        run_and_wait(c, "x", timeout_s=5, poll_s=0)
    assert "bad.xyz" in e.value.run.errors[0]
```

```python
# search/tests/test_retrieve.py
import json
from voltrieve_search.retrieve import retrieve

def body(partial=False):
    return {"response": [{"role": "assistant", "content": [{"type": "text",
             "text": json.dumps([{"ref_id": "0", "title": "voltrieve-fjord-specifications.pdf", "content": "Towing capacity: 2 100 kg"}])}]}],
            "activity": [{"type": "searchIndex", "id": 0, "count": 3}] + ([{"type": "searchIndex", "id": 1, "error": {"message": "timeout"}}] if partial else []),
            "references": [{"type": "searchIndex", "id": "0", "docKey": "k1", "rerankerScore": 3.1,
                            "sourceData": {"title": "voltrieve-fjord-specifications.pdf", "doc_type": "spec"}}]}

class Client:
    def __init__(self, status, payload): self.status, self.payload = status, payload; self.sent = None
    def post(self, path, b=None): self.sent = (path, b); return self.status, self.payload

def test_parses_chunks_and_references():
    c = Client(200, body())
    r = retrieve(c, "voltrieve-kb", "towing of the Fjord")
    assert r.chunks[0].content.startswith("Towing") and r.references[0].doc_key == "k1"
    assert r.partial is False
    assert c.sent[0] == "/knowledgebases/voltrieve-kb/retrieve"
    assert c.sent[1]["intents"] == [{"type": "semantic", "search": "towing of the Fjord"}]

def test_206_marks_partial_and_keeps_activity_errors():
    r = retrieve(Client(206, body(partial=True)), "voltrieve-kb", "q")
    assert r.partial is True
    assert any("error" in a for a in r.activity)
```

```python
# search/tests/test_smoke.py
import voltrieve_search.smoke as smoke
from voltrieve_search.smoke import run_smoke, SmokeQuestion
from voltrieve_search.retrieve import RetrieveResult, Reference

def ref(title, doc_type):
    return Reference(id="0", doc_key="k", reranker_score=3.0, source_data={"title": title, "doc_type": doc_type})

def test_smoke_passes_on_matching_reference(monkeypatch):
    monkeypatch.setattr(smoke, "retrieve", lambda c, kb, q: RetrieveResult([], [ref("voltrieve-fjord-specifications.pdf", "spec")], [], False))
    assert run_smoke(None, "kb", [SmokeQuestion("q", "fjord-specifications", "spec")])[0].passed

def test_smoke_fails_on_wrong_doc_type(monkeypatch):
    monkeypatch.setattr(smoke, "retrieve", lambda c, kb, q: RetrieveResult([], [ref("voltrieve-fjord-brochure.docx", "brochure")], [], False))
    assert not run_smoke(None, "kb", [SmokeQuestion("q", "fjord-specifications", "spec")])[0].passed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd search && uv run pytest tests/test_indexer.py tests/test_retrieve.py tests/test_smoke.py -q`
Expected: FAIL with import errors

- [ ] **Step 3: Implement upload, indexer, retrieve, smoke and the CLI subcommands**

`indexer.py`: `POST /indexers/{name}/run`, then poll `GET /indexers/{name}/status` until `lastResult.status` is `success`, `transientFailure` or `persistentFailure`. Error strings formatted `"{key}: {errorMessage}"`.

`retrieve.py`: parse `response[0].content[0].text` as JSON into `Chunk`s; `references` and `activity` as given.

`smoke.py`: iterate questions, call `retrieve`, evaluate the top five references, print a table of question, pass or fail, top titles.

`cli.py` subcommands: `upload` (env `STORAGE_ACCOUNT_NAME`, `DOCS_CONTAINER`; arg `--generated data/generated`), `index` (runs `run_and_wait`, prints the run, exits 1 on `IndexerFailed`), `retrieve "<question>"` (prints chunks and references as JSON), `smoke` (reads `search/smoke-questions.json`, exits 1 if any failed). All use `DefaultAzureCredential`.

`hooks/postprovision.sh`:

```sh
#!/bin/sh
set -eu
eval "$(azd env get-values)"
export STORAGE_ACCOUNT_NAME DOCS_CONTAINER STORAGE_RESOURCE_ID FOUNDRY_ENDPOINT EMBEDDING_DEPLOYMENT EMBEDDING_MODEL SEARCH_ENDPOINT
uv run --project search voltrieve-search upload --generated data/generated
uv run --project search voltrieve-search apply
uv run --project search voltrieve-search index
uv run --project search voltrieve-search smoke
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd search && uv run pytest -q`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add search hooks/postprovision.sh
git commit -m "Add document upload, indexer run, retrieve and smoke test" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Deploy end to end and record what was learned

**Files:**
- Create: `docs/deploy.md`
- Modify: `docs/decisions.md`, `README.md`

This task runs the real deployment. It is the verification of plan 1 and it produces the facts plan 2 needs.

- [ ] **Step 1: Provision and deploy**

Run: `azd up` (answers: environment `voltrieve-dev`, subscription, location `swedencentral`).
Expected: pre-provision prints the Entra ids and the test user password once; provisioning completes; the dealer image builds remotely and deploys; post-provision uploads 11 documents, applies six objects and the indexer reports `success` with `itemsFailed: 0`; after the dealer deploys, the `postup` hook prints 5 smoke passes.

The post-provision hook retries upload, apply and index every 60 seconds (up to 10 times) while role assignments propagate; note any wait in `docs/deploy.md`. The `azd up` order is preprovision, Bicep, postprovision, deploy, then the `postup` hook runs the smoke test. If post-provision still fails, wait and rerun `sh hooks/postprovision.sh`, and finish with `azd deploy` so the dealer image ships; then run `sh hooks/postup.sh`.

- [ ] **Step 2: Verify the dealer service in Azure**

Run: `curl -s "$(azd env get-value DEALER_URL)/healthz"` and `curl -s -o /dev/null -w "%{http_code}" "$(azd env get-value DEALER_URL)/stock"`
Expected: `{"status":"ok"}` and `401`

- [ ] **Step 3: Verify retrieval by hand**

Run: `eval "$(azd env get-values)" && export SEARCH_ENDPOINT && uv run --project search voltrieve-search retrieve "Which of the 84 kWh Voltrieve models tows more?"`
Expected: references from both `ragn-specifications` and `fjord-specifications`, with the towing figures 1 800 kg and 2 100 kg in the chunk contents.

- [ ] **Step 4: Verify the knowledge base MCP endpoint answers**

Run:
```bash
curl -s -X POST "$(azd env get-value SEARCH_ENDPOINT)/knowledgebases/voltrieve-kb/mcp?api-version=2026-04-01" -H "Authorization: Bearer $(az account get-access-token --scope https://search.azure.com/.default --query accessToken -o tsv)" -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```
Expected: a tool list containing `knowledge_base_retrieve`. Record the exact response shape in `docs/decisions.md` (plan 3 attaches this endpoint to the prompt agent).

- [ ] **Step 5: Write the documentation**

`docs/deploy.md`: prerequisites (Azure CLI, azd, uv, Docker optional, Global Administrator in the tenant), the three commands (`azd auth login`, `az login`, `azd up`), what each hook does, how to rerun a hook, how to run the dealer service locally (`uv run uvicorn app.main:app` with `TENANT_ID` and `DEALER_CLIENT_ID` exported), how to tear down (`azd down --purge`), and the known waits (role propagation, indexer run time).

`docs/decisions.md`: region chosen and why; chat and embedding model names and versions actually deployed; Search api-version used and any object that needed a preview version; whether `/document/content` was the right SplitSkill input for blob content (if the indexer produced empty chunks, the corrected path); the MCP `tools/list` response; the observed indexer run time.

`README.md`: update the status line to "plan 1 complete" and link `docs/deploy.md` and `docs/decisions.md`.

- [ ] **Step 6: Em-dash check and commit**

Run: `git grep -nP '(*UTF)\x{2014}' -- . ':!data/generated/*.pdf' ':!data/generated/*.docx'`
Expected: no output

```bash
git add docs README.md
git commit -m "Document deployment and record foundation decisions" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- Spec coverage for plan 1 scope: section 4 (domain, documents, test cases, dealer service) in Tasks 1, 2, 4; sections 6.1 and 6.4 (app registrations, Search service-to-service roles) in Tasks 5, 6; section 7 (Search built by hand in order) in Tasks 7, 8; section 12 (Bicep, azd, hooks) in Tasks 6, 8, 9; section 14's smoke test in Tasks 8 and 9. Deferred to plan 2: the Web API, its roles (Foundry User, Search Index Data Reader, `Dealer.Access` assignment to its identity via `voltrieve-entra assign-app-role`), `api` and `web` services in `azure.yaml`, the Static Web App, SPA redirect URIs. Deferred to plan 3: prompt agent, hosted agent, runbook, comparison.
- Review Focus 1: Task 3 `test_v1_style_audience_accepted`; 2: Task 4 `test_booking_validation`; 3: Task 8 `test_per_document_failures_raise_with_keys`; 4: Task 8 `test_206_marks_partial_and_keeps_activity_errors`; 5: Task 5 `test_setup_twice_yields_same_ids_and_no_duplicates`.
- Names used across tasks: `load_catalog`, `Catalog.by_slug`, `generate_all`, `manifest.json` fields `file`, `model_slug`, `doc_type` (Task 2 to Task 8 upload); `TokenValidator`, `AuthError`, `Settings`, `create_app` (Task 3 to Task 4); `SearchRestClient.put/post/get`, `render`, `apply_all`, `DEFINITION_ORDER` (Task 7 to Task 8); object names `voltrieve-docs-ks`, `voltrieve-kb` (Task 7 to Task 8 and plans 2 and 3); Bicep outputs including `EMBEDDING_MODEL` (Task 6 to the Task 8 hook).
