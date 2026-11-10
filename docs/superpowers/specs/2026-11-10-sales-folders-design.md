# Voltrieve sales folders and car identities

Design document, 2026-11-10. Status: draft for approval.

## 1. Intent

Give Voltrieve the kind of sales material you get from a dealership when you
are about to buy a car: a folder per model with a brochure, a price list, an
equipment comparison and the technical data, plus brand-wide documents on
warranty and charging. They are written as Markdown, turned into
good-looking PDFs, and indexed.

Why:

1. **Better test material.** Today each model has a short Word brochure and a
   one-page spec PDF (about 2 KB). Real sales documents have price tables,
   equipment matrices and fine print across many pages, which is exactly
   where RAG usually starts to fail.
2. **Something worth linking to.** Issue #2 (source links) needs documents a
   customer would actually want to open: "which car suits me?" should come
   back with the right brochure and price list.
3. **A fixed look for every car.** Each model gets a defined appearance, with
   a reference image that every later image is generated from. A Fjord has to
   be recognizable as a Fjord in every picture, in the folders now and in
   issues #3, #4 and #6 later.

## 2. Goals, non-goals, anti-goals

**Goals**

- One sales folder per model (5 models) and three brand-wide documents.
- A car identity sheet per model: shape, light signature front and rear,
  colors, wheels per trim, interior, plate. Bold enough to tell the cars
  apart at a glance, not so wild that they look like concept cars.
- Photorealistic images, of the cars and of the places they are in.
- One source of truth: the facts in the documents come from
  `data/voltrieve.yaml`, so the brochure, the price list, the spec sheet and
  the agent's pricing tool can never disagree.
- The new PDFs replace today's brochures and spec sheets in the index.

**Non-goals**

- The bigger spare parts catalog. That is the next design, done separately.
  The accessories pages in this design use the current parts data and are
  regenerated when the catalog grows.
- Issues #1 and #2. They come after this and the parts catalog.
- Swedish versions. English first, like all current documents.
- Image or 3D answers in the chat (issues #3 and #7).

**Anti-goals** (failures even if it technically works)

- A car that looks like a real brand's car or carries a real logo.
- Images that look like CGI or clip art.
- The same car looking different from one image to the next.
- Documents that contradict each other or the pricing tool.
- Claims a fictional brand cannot make, such as a Euro NCAP rating.

## 3. What we learned from BMW and Volvo

Studied the Swedish pages for the BMW iX3 and the Volvo EX30
(November 2026). What they have in common, and what we take:

| They do | We do |
|---|---|
| Lead with three or four headline numbers (range, charge time, power, 0 to 100) | A headline strip on the brochure cover spread and on each trim page |
| Price "from", plus a monthly leasing or loan figure with full fine print (rate, deposit, residual, total cost) | Price list with cash price and a worked financing example, with fine print, from a fictional Voltrieve Financial Services |
| Trims that build on each other ("Core features, plus...") | Three trims per model: **Pure**, **Plus**, **Prime**, each listing what it adds |
| Named colors ("Ocean Wave Blue metallic", "Cloud Blue") and named wheel designs ("Star-spoke style 1045", sizes 18 to 20) | Named colors and named wheels per model, with prices |
| A signature light ("Thor's hammer", "Iconic Glow") as the face of the car | A signature light front and rear per model (section 4) |
| Practical numbers sold as features: boot and frunk litres, folded-seat volume, towing | The same, in the brochure and in the spec sheet |
| An FAQ (range, charging time, charging cost, where to charge) | An FAQ page in each brochure |
| Company car benefit value (BMW shows "förmånsvärde") | A company car row in the Swedish price list |
| Legal footnotes: WLTP, "pictured features may not be standard" | Same footnotes, worded for Voltrieve |

## 4. The cars

Five cars, five silhouettes, five light signatures, five hero colors. The
brand ties them together: no front grille, a small backlit V chevron emblem
centered on the front and the tailgate, black or body-colored lower
cladding, white EU plates with the model name.

Reference images from the first test are in `data/design/reference/`
(section 5). The prompt text for each car lives in one file,
`data/design/cars.yaml`, and every image prompt is built from it.

### Voltrieve Spark, city car

- **Shape:** 3.7 m, five doors, tall upright rounded box ("a pebble"), very
  short overhangs, wheels at the corners, near-vertical tailgate.
- **Front signature:** two large round headlamps, each a thin white LED ring
  with a dark center, wide apart in a smooth closed front panel.
- **Rear signature:** two round LED ring tail lamps matching the front.
- **Hero color:** Saffron (warm yellow, solid) with a gloss white roof and
  white mirror caps.
- **Other colors:** Snow (white, black roof), Fjäll Mint (pale green, white
  roof), Graphite (dark grey, white roof).
- **Wheels:** Pure and Plus: 17 inch "Pebble" aero covers, white and light
  grey with five small holes. Prime: 17 inch "Pebble" in graphite.
- **Cladding:** thick matte black on lower doors and wheel arches.
- **Interior:** light grey recycled textile, pale wood dash strip.
- **Plate:** SPARK.

### Voltrieve Lumen, hatchback

- **Shape:** 4.3 m, five-door fastback hatchback, low roofline, long
  wheelbase, sculpted hood, frameless door glass.
- **Front signature:** two very thin parallel LED lines stacked across the
  full front width, no separate headlamp housings.
- **Rear signature:** the same double line across the full tailgate, in red.
- **Hero color:** Coral (red-orange metallic) with a gloss black glass roof
  and black mirror caps.
- **Other colors:** Pearl (white), Midnight (near-black blue), Silver Birch
  (light silver).
- **Wheels:** Pure: 18 inch "Arc" five double spokes, silver. Plus and Prime:
  19 inch "Turbine", ten thin twisted spokes, diamond-cut silver and gloss
  black.
- **Interior:** black and coral stitching, sport seats on Prime.
- **Plate:** LUMEN.
- **Note from the test:** the first image read as a large sedan. The prompt
  needs "compact" and "hatchback tailgate" stressed.

### Voltrieve Ragn, crossover

- **Shape:** 4.6 m rugged crossover, tall and boxy, squared wheel arches,
  high ground clearance, black roof rails.
- **Front signature:** four square pixel headlamps, two side by side on each
  side, in a flat black front band, and two orange recovery hooks in the
  lower bumper.
- **Rear signature:** four square pixel tail lamps mirroring the front, and
  an orange tow eye.
- **Hero color:** Moss (deep olive green, satin finish).
- **Other colors:** Granite (mid grey, satin), Sand (warm beige), Night
  (black).
- **Wheels:** Pure and Plus: 19 inch "Trail", five thick spokes, gunmetal, on
  all-terrain tires. Prime: 20 inch "Trail" in matte black.
- **Cladding:** wide matte black textured cladding on arches and sills.
- **Interior:** washable dark grey textile, orange pull loops.
- **Plate:** RAGN.

### Voltrieve Fjord, estate

- **Shape:** 4.9 m, long and low estate, long flat roof, gently sloping rear
  window, slim satin aluminium roof rails and window trim.
- **Front signature:** one thin continuous LED line across the full width
  that dips into a shallow V in the center around the emblem, like the
  outline of a fjord valley.
- **Rear signature:** one thin red line across the full tailgate width with
  the same V dip as the front, ending in short horizontal blades that wrap
  around the rear corners. **No vertical pillar lights:** the scene test
  used tall lights down the rear pillars, and that reads as a Volvo estate.
- **Hero color:** Glacier Blue (deep blue metallic).
- **Other colors:** Frost (white metallic), Slate (dark grey metallic), Heath
  (deep burgundy metallic).
- **Wheels:** Pure: 19 inch "Birch", ten spokes, silver. Plus and Prime: 20
  inch "Fern", fifteen thin straight spokes, diamond-cut silver.
- **Interior:** light wool blend and pale ash wood, Nappa leather on Prime.
- **Plate:** FJORD.

### Voltrieve Atlas, large SUV

- **Shape:** 5.1 m, seven seats, upright stance, long flat clamshell hood,
  tall flat roof, "floating roof" with all pillars blacked out.
- **Front signature:** tall vertical bracket-shaped light columns at the
  front corners, "[" on the left and "]" on the right, framing a wide smooth
  closed front panel.
- **Rear signature:** the same bracket columns at the rear corners.
- **Hero color:** Glacier White (white pearl) with a gloss black roof and
  brushed copper accents on the lower bumper and sills.
- **Other colors:** Basalt (dark graphite, copper accents), Forest (dark
  green, copper accents), Obsidian (black, black accents).
- **Wheels:** Pure: 21 inch "Monolith", six wide aero spokes, silver. Plus and
  Prime: 22 inch "Monolith" two-tone, gloss black with machined silver faces.
- **Interior:** cognac leather on Prime, three rows, third row for two.
- **Plate:** ATLAS.

### Colors and prices

Every model has one hero color included in the price and three options. The
price of a color goes in `data/voltrieve.yaml` (suggested: solid colors free,
metallic and pearl 9,900 SEK / 900 EUR, satin 14,900 SEK / 1,350 EUR). The
color names are also what issue #6 (recolor) will accept.

## 5. Images

### How consistency works

1. **Two studio masters per car:** front three-quarter and rear
   three-quarter, light grey studio, 1536 x 1024, highest quality. These are
   the templates. They are reviewed by you and checked in under
   `data/design/reference/`.
2. **Every other image is an edit from the masters** (`ailloy image --ref`),
   with the car's identity text from `cars.yaml` repeated in the prompt, plus
   the scene. The model draws the same car into a new place.
3. **Variants of the same car** (other colors, other wheels) are edits from
   the master with only that detail changed.
4. **A check after each image:** an automatic yes/no question per image
   ("Is this the same car as in the reference: same light signature, same
   wheels, same color?") with `ailloy eval --attach`, and a contact sheet per
   model for you to look over. Failures are regenerated, at most twice.

Things learned from the spike:

- `gpt-image-2.5-flare` makes very convincing studio images and follows the
  identity text well. All five cars came out distinct on the first try.
- It does **not** accept the input fidelity setting (HTTP 400), so
  consistency rests on the reference image plus the identity text. The scene
  test (section 10) shows how well that holds.
- Rear designs must be defined in the text: the model invents them otherwise.
- Plates come out right with short words like the model names.
- **Scene test passed:** the Fjord along a fjord (rear view) and the Spark in
  Stockholm's old town (front view), each made from its studio master, are
  clearly the same cars: same paint, wheels, trim, lights and plate. Both
  are in `data/design/reference/`.
- **Check every design against real cars.** The Fjord's first rear design
  looked like a Volvo, so it was changed (section 4). The review of the 10
  masters should ask this for each car.

### Images per model

| Image | Used in |
|---|---|
| Hero: the car in its home landscape | Brochure cover, top of price list |
| Front three-quarter, outdoors | Brochure, design spread |
| Rear three-quarter, outdoors | Brochure, design spread |
| Side profile, studio | Spec sheet, dimensions drawing background |
| Interior, driver's view | Brochure, interior spread |
| Light signature close-up at dusk | Brochure, design spread |
| Wheel close-up for each wheel design | Price list, wheels section |
| Charging at a public charger | Brochure, charging page |
| Practical shot: boot loaded, frunk open, or roof box | Brochure, practicality page |
| Each of the three optional colors, studio | Price list, colors section |

About 12 images per model, 60 in total, plus 10 studio masters.

**Home landscapes** (photorealistic, Scandinavian, different per car):
Spark in Stockholm's old streets, Lumen on a coastal road on the Swedish west
coast, Ragn on a forest gravel road in Jämtland, Fjord along a Norwegian
fjord, Atlas outside a mountain lodge in winter.

### Rules for every image

- Photorealistic press-photo style: real lenses (35 to 85 mm), real light,
  real reflections, no CGI sheen.
- No people in focus, no real brands or logos anywhere (shop signs, chargers,
  roof boxes), no text other than the plate.
- Charger in the charging shot is a generic Voltrieve-branded unit.
- Stored as WebP, 1600 px wide for documents, plus the PNG master.

## 6. The sales folder

### Per model (5 x 4 documents)

1. **Brochure**, 10 to 12 pages, landscape A4:
   cover with hero image and tagline; headline numbers; design (front, rear,
   light signature); interior; technology and Voltrieve Pilot; range and
   charging, with the charging curve as a chart; practicality (boot, frunk,
   towing, roof load); the three trims at a glance; colors and wheels; FAQ;
   back cover with "book a test drive" and the dealer contact.
2. **Price list and equipment**, 4 to 6 pages, portrait A4:
   prices per trim and drive (SEK and EUR); what each trim adds; full
   equipment matrix (standard, optional with price, not available); option
   packs; colors and wheels with prices; company car benefit value (Sweden);
   a worked financing example with full fine print; validity date.
3. **Technical specifications**, 2 to 3 pages, portrait A4:
   replaces today's spec PDF. Dimensions with a side-view drawing, weights,
   battery, charging (AC and DC, the 10 to 80 % time and the curve as a
   table), performance per drive, towing, volumes.
4. **Accessories**, 2 to 4 pages, portrait A4:
   roof box, tow bar, chargers, mats, wheels and tires, with article numbers
   and prices from the parts data.

### Brand-wide (3 documents)

5. **Warranty and service plans:** new car warranty, battery warranty,
   service intervals and plans, roadside assistance.
6. **Charging guide:** home charging, public charging, costs, tips for winter.
7. **Buyer's guide:** today's Markdown buyer's guide, comparing all five
   models, turned into a PDF in the same style.

That is 23 PDFs.

### Look

- A clean Nordic style: lots of white space, one sans-serif family, large
  photos, thin rules, tables that read like a real price list.
- Each model uses its hero color as the accent color in its own folder; the
  brand-wide documents use Voltrieve ink black.
- Same cover, header, footer and footnote style across all documents.

## 7. How the documents are made

1. **Facts in YAML.** `data/voltrieve.yaml` grows with everything the
   documents need: trims with what they add and their price, colors, wheels,
   interiors, dimensions, weights, volumes, accessories, warranty terms,
   service plans and financing terms. Nothing in a document is typed by hand
   if it is a number.
2. **Markdown from templates.** The generator (`data/generator`) renders one
   Markdown file per document from templates plus the YAML. The Markdown is
   kept in the repo, so changes are readable in diffs.
3. **PDF from Markdown.** Markdown becomes HTML with a shared stylesheet and
   then PDF through headless Chromium (builder's call: Playwright's Chromium,
   since it prints CSS layouts reliably; WeasyPrint is the alternative).
4. **Output:** `data/generated/sales/<model>/<document>.pdf` and
   `data/generated/sales/brand/<document>.pdf`, uploaded to the documents
   container as today.
5. **Images** come from `data/design/images/`, generated by a separate,
   rerunnable script that skips images that already exist, so documents can
   be rebuilt without paying for images again.

## 8. Indexing and the agent

- The 23 PDFs **replace** today's Word brochures and spec PDFs. The service
  guide stays as it is.
- `doc_type` gets new values: `brochure`, `price_list`, `specifications`,
  `accessories`, `warranty`, `charging_guide`, `buyers_guide`.
  `model_slug` is set for the per-model documents.
- **Tables are the risk.** The indexer reads PDFs with default parsing, which
  flattens tables. First step after the first PDF exists: index it and ask
  equipment and price questions. If the answers get rows and columns mixed
  up, choose one of: (a) the Document Layout skill, which keeps tables
  (costs per page, small for about 150 pages), or (b) index the Markdown
  source next to the PDF and link to the PDF. Decided by that test, written
  down in `docs/decisions.md`.
- **Warranty becomes documented.** `not_documented` in `voltrieve.yaml`
  lists `warranty` today, and the tests expect the agent to say it does not
  know. That entry goes, and those tests become warranty questions with real
  answers. Euro NCAP, crash tests, factory and production stay undocumented.
- **The pricing tool** (`get_prices`) and the price list read the same YAML,
  so they agree by construction. Add a test that compares them.
- All sales documents are `linkable` for issue #2.

## 9. Tests

New questions in `tests/routing/questions.yaml`, at least:

- price of a trim with a drive and a color ("Fjord Plus AWD in Heath")
- what a trim adds over the one below
- which trims have a given item as standard
- wheel sizes and names per trim
- boot, frunk and folded-seat volumes
- the financing example's monthly cost, and that the agent quotes the fine
  print terms rather than inventing a rate
- warranty and battery warranty
- comparing two models on range, price and boot
- questions the folders still do not answer (Euro NCAP) must still get "not
  documented"

The whole suite runs on all three backends before and after, compared with
the Terra baseline in `docs/evidence/models/final-gpt-6.1-terra.json`.

## 10. Costs

- **Spike so far:** 9 generation calls, 7 images (5 studio masters, 2 scene
  tests; 2 calls failed on the fidelity setting).
- **Images:** about 70 images at high quality, plus retries, so plan for
  about 100 generations. `gpt-image-2.5-flare` is not in the Azure retail
  prices API yet. At `gpt-image-1` list prices, a high-quality 1536 x 1024
  image is roughly 0.25 USD, so about 25 USD as a ceiling. To confirm before
  the full run: generate the 10 masters, read the actual charge in Cost
  Management the next day, and get your approval for the rest.
- **Indexing:** embeddings for about 150 pages are cents. The Document Layout
  skill, if chosen, is about 1.5 USD per 100 pages.
- **Tests:** one full routing run on three backends, as before.

## 11. Order of work

1. Identity sheets in `cars.yaml`, the 10 studio masters, your review.
2. Extend `voltrieve.yaml`; templates and the PDF pipeline with placeholder
   images; one Fjord folder end to end.
3. Index the Fjord PDFs and run the table test (section 8). Decide parsing.
4. Cost check, your approval, then all scene images.
5. All 23 PDFs, reindex, new tests, full suite on all three backends.

## 12. Calls made in review (check these)

A reviewer read this design as the builder. These are the answers, all my
calls rather than yours:

1. **Prices.** Today's `price` per model becomes the **Pure** price in the
   cheapest drive (RWD, or AWD for Ragn and Atlas, which are AWD only), so
   existing price answers and tests stay valid. **Plus** is about 8 % and
   **Prime** about 16 % above Pure, rounded to 1,000 SEK and 100 EUR. The
   AWD surcharge stays as it is.
2. **`get_prices` and the dealer service do not change in this work.** They
   keep returning the model's entry price, which equals Pure. Trim, color and
   option prices come from the price list PDF. The new test checks that the
   price list's Pure price equals the dealer's list price for every model
   and market. Extending the tool with trims is a later, separate change.
3. **Trim contents** are authored by the builder in `voltrieve.yaml`, and must
   agree with what is there today: `heat_pump_standard`, the option packs per
   model, `pilot_version`. Rule of thumb: Pure is well equipped, Plus adds
   comfort (the Winter pack contents, power tailgate, larger wheels), Prime
   adds the Sound pack, Pilot Plus where available, and the premium interior.
   A pack that becomes standard on a trim is listed as "included" there.
4. **Company car benefit value** (förmånsvärde) is a plausible, clearly
   fictional monthly figure with a footnote saying it is an example. Sweden
   only; the EU price list has no such row.
5. **Rear masters** are made as edits from the front master plus the rear
   description in the text. I generate and regenerate masters until they
   pass my own check, including "does this look like a real brand's car?",
   then **work stops for your review** of all 10. Nothing after step 1 runs
   before you approve them.
6. **`data/design/cars.yaml`** holds only image prompt text: shape, lights,
   cladding, interior, home landscape, plate. Color names, wheel names and
   prices live in `voltrieve.yaml` only, and `cars.yaml` refers to them by
   key. The builder writes it from section 4.
7. **`linkable` is not added now.** It belongs to issue #2. New `doc_type`
   values need no index change, since the field is already filterable.
8. **Warranty tests:** both suites are in scope. `ragn-warranty` in
   `tests/grounding/questions.yaml` becomes a documented warranty question.
   Warranty terms are invented by the builder, plausible for an EV brand.
9. **Image budget:** the 10 masters may run as part of step 1 (about 3 USD).
   Everything after that needs your approval with the measured cost. Hard
   ceiling for this project: **40 USD** of image generation, retries
   included. If edits from a reference fail for some scene, fall back to text
   only with the full identity text, and flag those images on the contact
   sheet.
10. **Old documents:** the Word brochures and the old spec PDFs are removed
    from `data/generated/`, from `manifest.json` and from the blob container,
    and the indexer is reset and rerun so nothing stale stays in the index.

## 13. Left to the builder

- Exact page layouts, typeface (one open-license sans-serif, bundled in the
  repo) and chart style.
- Exact dimensions, weights and volumes, as long as they are plausible for
  the segment and consistent with the existing range and battery data.
- Wording of brochure copy, FAQ answers and fine print.
- Financing terms (rate, deposit, residual), clearly fictional.
- Contact sheet format for image review.
