# Spare parts expansion and parts stock: design

Status: draft for approval, 2026-11-10.

## 1. Why

Owners and workshops ask for parts the catalog does not have yet (tyres, buttons, levers,
indicators, side windows), and they want to know where a part can be picked up. Two example
questions from the product owner, with the answers they expect:

- "I've broken my right side mirror on my Spark, do you have any of those in stock in
  Stockholm?" Expected: "Yes, there are 5 in stock in Stockholm", or, when Stockholm has none,
  where the closest dealer that has it is.
- "My windscreen wiper needs replacing, what's the article number?" Expected: "For your Fjord
  you need wiper blades with article number VP-....."

Today the catalog has 429 parts (66 kinds of parts) in 5 catalogs, and the dealer service only
knows the stock of whole cars.

## 2. Goals

1. **Broader coverage:** about 300 to 400 new article numbers, bringing the catalog to about
   750 to 800 parts (section 4).
2. **Parts stock per dealer:** the dealer service knows how many of each article are in stock in
   each of the four dealer cities, and the agent can ask for it (section 5).
3. **Closest dealer with stock:** when the city the customer named has none, the agent says
   which other dealers have it, closest first, with the distance between the two dealers
   (section 5).
4. All three backends (own loop, prompt agent, hosted agent) get the same behaviour.

## 3. Non-goals and anti-goals

**Not in this work:**
- Diagnosing symptoms ("a rattling noise in the wheel house"). That is issue #11.
- Part images (issue #3), ordering or reserving parts, delivery times, prices for spare parts.
- More dealer cities.

**Would make it a failure even if it works:**
- **Existing article numbers change.** They are in the indexed parts catalogs, the accessories
  catalogs of the sales folders, recorded evidence and people's notes. Every existing article
  number must stay exactly as it is.
- **The agent states a distance from the customer.** The agent does not know where the customer
  is. A distance is always between two dealers, worded as such ("Uppsala, about 70 km from
  Stockholm"), and only when the customer named a city.
- **The agent invents stock, a delivery time or a part.** Stock comes from the dealer service
  only. If no dealer has the part, the agent says so plainly.
- **Parts that an electric car does not have.** There is no engine oil and no gear shift knob.
  Asked for engine oil, the agent says the car uses none (the only oil is the reduction gear
  oil); asked for a gear knob, it offers the drive selector.

## 4. The new parts

Decided with the product owner. The kinds below are required; the builder sets the exact list
and specs so the total lands in the 300 to 400 range.

- **Tyres:** summer tyres and Nordic winter tyres, studded and studless, sold one per article
  (quantity 1), in the exact size of each wheel in the catalog. Each wheel of each model gets a
  tyre size in `data/voltrieve.yaml` (for example Fjord 19 inch Birch and 20 inch Fern have
  different sizes). The tyre's spec names the size and the wheels it is for, so "winter tyres
  for my Fjord Plus" finds the 20 inch tyre, through the trim's wheel.
- **Interior controls:** the drive selector (per model: a stalk or a rotary dial, set in the
  catalog), the indicator stalk, the wiper stalk, window switches (the driver's switch pack and
  the single switch per other door), the hazard switch, the steering wheel button packs (left
  and right), seat adjustment switches (left and right).
- **Lighting:** front indicators and side repeaters (left and right), plus other small lamps the
  builder finds missing, such as reversing and rear fog lamps.
- **Glass:** door windows per corner, rear quarter glass where the body has it, and the
  panoramic roof glass for the models whose trims include the panoramic glass roof.
- **Wipers and washers:** what is missing around the existing wiper blades, such as the rear
  wiper blade, wiper motors, the washer pump and washer nozzles.
- **Searchable everyday words:** the catalog uses the right term, but the text includes the word
  people use, so a search finds it: "wheel nut" finds the wheel bolt set, "windshield" finds the
  windscreen, "blinker" and "direction light" find the indicators.
- **No engine oil, no gear knob:** the service items catalog says in plain words that Voltrieve
  cars have no engine oil, and the interior catalog says the drive selector replaces the gear
  lever.

**Article numbers are append-only.** Today numbers are handed out in template order
(`VP-10007` plus 13 for each part), so inserting a template renumbers everything after it. The
builder changes the numbering so that every existing part keeps its number and new parts get
new numbers, for example by numbering new templates after the highest existing number. A test
pins this: every article number in today's `data/generated/parts-index.json` still belongs to
the same part key and vehicles after the change.

New kinds may go into the existing catalogs or into new ones (for example an interior catalog
and a wheels and tyres catalog). If a catalog is added or renamed, the parts knowledge base,
knowledge source, index and data source descriptions, and the `search_spare_parts` tool
description, must name what the parts base now holds (the lesson from the sales folders, where
the documents descriptions went stale).

## 5. Parts stock and the closest dealer

**Data.** The dealer service gets the stock of every article in each of the four cities
(Stockholm, Göteborg, Malmö, Uppsala), and the road distances between the four cities. Stock is
generated from the parts data, deterministic (the same input gives the same stock), never typed
by hand. Builder's call how it is generated, within these rules:
- most parts are in stock in at least one city;
- some parts are out of stock everywhere;
- some parts are in stock in exactly one city;
- **pinned for the product owner's example:** the Spark right door mirror is out of stock in
  Stockholm and in stock in Uppsala and at least one other city.

Distances (approximate road distances, in `data/voltrieve.yaml` or the dealer data): Stockholm
to Uppsala 70 km, Stockholm to Göteborg 470 km, Stockholm to Malmö 615 km, Uppsala to Göteborg
455 km, Uppsala to Malmö 680 km, Göteborg to Malmö 270 km.

**Dealer service.** A new protected endpoint, for example `GET /parts/stock?article=VP-10007&city=Stockholm`, with the same authorization as `/stock`. It returns the stock of that article in
every city. With a city, the named city comes first and the others follow by distance from it,
each with its distance from the named city. Without a city, the cities with stock come first, no
distances. An unknown article is an error the tool reports as "not a Voltrieve article number".

**Agent tool.** A new server tool, for example `check_part_stock(article, city?)`, defined once
in `agent_core` so the own loop, the prompt agent (as a function tool) and the hosted agent all
get it, the way they get `check_stock`. Its description says to find the article number with
`search_spare_parts` first. The agent instructions say how to answer:
- named city has it: the number in stock there;
- named city has none: the closest dealer that has it, with the number and its distance from the
  named city, and the other dealers that have it;
- no dealer has it: say so, invent no delivery time;
- no city named: the cities that have it, no distances, and ask which suits them if that helps.

## 6. Tests

All expected values are derived from the data at run time, never written as literals in the
question files.

- **Generator:** the append-only article number test (section 4); tyre sizes per wheel; every
  model gets the new kinds that apply to it; the panoramic roof glass only for models that have
  that trim item; the "no engine oil" and "drive selector" wording is in the catalogs.
- **Dealer service:** the endpoint's order and distances; an unknown article; the stock rules in
  section 5, including the pinned Spark mirror.
- **Agent core:** the new tool's schema, description and call.
- **Routing suite** (`tests/routing/questions.yaml`), new questions, for example: the Spark right
  mirror in Stockholm (expects the parts base and the stock tool), wiper blades for the Fjord
  (parts), winter tyres for the Fjord Plus (parts, and the docs base or the trim's wheel through
  the catalog, builder's call on what "right" is), a window switch, an indicator. The routing
  checker learns to count the stock tool.
- **Grounding suite:** answers for those questions checked against the data: the stock number in
  the named city, or the closest dealer with stock and its distance; the tyre size for a trim;
  "engine oil" gets "no engine oil" and no invented article.
- Run on all three backends, compared with
  `docs/evidence/models/descriptions-gpt-6.1-terra.json`.

## 7. Costs

No new Azure resources and no images. More parts chunks to index, a small change in Search
cost. One extra tool call on stock questions.

## 8. Calls made after the builder check

These were settled by the designer, not by the product owner, and can be changed on review.

1. **Single tyres and the winter wheel sets.** The accessories catalogs keep their complete winter
   wheel sets (VA-910x) as they are. The new VP- tyres are sold one at a time for every wheel. A
   test checks that each wheel set's size and wheel name match a wheel of that model in the
   catalog. For "winter tyres for my Fjord Plus" a right answer gives the tyre size for the
   Plus's wheel (20 inch Fern) and may also mention the complete wheel set; the grounding check
   requires the right size and article, and does not require or forbid the wheel set.
2. **The pinned mirror** is `door_mirror_right` for the Spark (the whole mirror). The mirror glass
   is not pinned; an answer that also mentions the glass is fine.
3. **Where stock lives.** The generator writes the parts stock and the distances to a committed
   file in the dealer service (next to `data.json`, which keeps the car stock and prices), and a
   test fails if the committed file differs from what the generator produces.
4. **New catalog fields are fine:** a tyre size per wheel, a drive selector type per model, and a
   flag for rear quarter glass per model, validated like the other catalog fields.
5. **Existing parts may get better text** (for example "wheel nut" in the wheel bolt set, or
   "windshield" in the windscreen), as long as their key, fits and article number stay the same.
6. **Routing counts the stock tool as its own expectation:** a question can list the tools it
   needs (for example `tools: [check_part_stock]`) next to the sources, and the run is right only
   when both match. The stock tool is not a search.
7. **When the answer depends on something the customer did not say** (side, trim or drive), the
   agent gives the options briefly with what each depends on, or asks, instead of guessing one.
   The test questions name enough to have one right answer, plus one question that leaves out
   the trim on purpose and expects the tyre size for each trim.

## 9. Left to the builder

- The exact part list, names and specs within section 4.
- How stock is generated, within the rules in section 5.
- The endpoint path and the tool name and wording.
- Whether new kinds go into existing catalogs or new ones.
