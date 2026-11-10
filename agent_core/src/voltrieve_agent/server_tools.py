"""Tools the agent runs on the server: knowledge base search and dealer operations."""

import datetime
from zoneinfo import ZoneInfo

from voltrieve_agent.curated import CURATED_ANSWERS, FinalAnswer, curated_description
from voltrieve_agent.dealer import DealerClient
from voltrieve_agent.knowledge import (
    KNOWLEDGE_BASE_NAME,
    PARTS_KNOWLEDGE_BASE_NAME,
    KnowledgeBase,
)
from voltrieve_agent.tools import ServerTool, UserContext

BOOK_ROLE = "TestDrive.Book"
CURATED_TOOL = "get_curated_answer"
KB_SEARCH_TOOL = "search_voltrieve_docs"
PARTS_SEARCH_TOOL = "search_spare_parts"
# Prompt agents get the knowledge bases as MCP tools instead, so they drop these.
KB_SEARCH_TOOLS = (KB_SEARCH_TOOL, PARTS_SEARCH_TOOL)
# The model routes on these words alone, so each says what its base holds and what it does not.
DOCS_DESCRIPTION = (
    "The Voltrieve product and workshop documents. Per model: the sales brochure, the price list "
    "(trims, colors, wheels, option packs and a financing example), the technical specifications "
    "and the accessories catalog. For all models: the buyer's guide, the charging guide, the "
    "warranty and service plans, and the service guide. Use for features, specifications, "
    "prices, equipment per trim, accessories, financing, warranty, charging and what a repair or "
    "service job consists of. It lists article numbers only for accessories; spare part article "
    "numbers are not here."
)
PARTS_DESCRIPTION = (
    "The Voltrieve spare parts catalogs: brakes, suspension and steering, body, glass and "
    "lighting, electrical and charging, service items, wheels and tyres, and interior and "
    "controls. Article numbers, part descriptions, positions on the car and the vehicles each "
    "part fits. Use to find a part or an article number. It does not say which parts a job needs "
    "or how to do the work, and it has no stock: check_part_stock has that."
)
SEARCHING_DOCUMENTS = ("searching_documents", "Searching the documents")
SEARCHING_PARTS = ("searching_parts", "Searching the parts catalog")
# Prompt agents run their searches in Foundry, so these statuses go by knowledge base.
KB_STATUSES = {KNOWLEDGE_BASE_NAME: SEARCHING_DOCUMENTS, PARTS_KNOWLEDGE_BASE_NAME: SEARCHING_PARTS}
# The dealer works in Swedish local time, whatever the timezone of the host.
DEALER_TIMEZONE = ZoneInfo("Europe/Stockholm")

# The dealer service takes slugs and exact city names, so the model is given the valid values.
MODEL_SLUGS = ["spark", "lumen", "ragn", "fjord", "atlas"]
CITIES = ["Stockholm", "Göteborg", "Malmö", "Uppsala"]
MODEL_PROPERTY = {"type": "string", "enum": MODEL_SLUGS, "description": "Model slug"}
CITY_PROPERTY = {"type": "string", "enum": CITIES}


def build_server_tools(
    dealer: DealerClient, search: KnowledgeBase, parts: KnowledgeBase | None = None
) -> list[ServerTool]:
    async def search_docs(args: dict, user: UserContext) -> str:
        return await search.search(args["query"])

    async def search_parts(args: dict, user: UserContext) -> str:
        return await parts.search(args["query"])

    async def check_stock(args: dict, user: UserContext) -> str:
        return await dealer.stock(args.get("model"), args.get("city"))

    async def check_part_stock(args: dict, user: UserContext) -> str:
        return await dealer.part_stock(args["article"], args.get("city"))

    async def get_prices(args: dict, user: UserContext) -> str:
        return await dealer.prices(args.get("market", "SE"))

    async def book_test_drive(args: dict, user: UserContext) -> str:
        # The requester is the signed-in user, never something the model supplies.
        return await dealer.book(args["model"], args["city"], args["date"], user.oid)

    async def get_current_date(args: dict, user: UserContext) -> str:
        return datetime.datetime.now(DEALER_TIMEZONE).date().isoformat()

    async def get_curated_answer(args: dict, user: UserContext) -> str:
        return FinalAnswer(CURATED_ANSWERS[args["topic"]].text)

    def schema(properties: dict, required: list[str] | None = None) -> dict:
        return {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        }

    return [
        ServerTool(
            CURATED_TOOL,
            curated_description(),
            schema({"topic": {"type": "string", "enum": list(CURATED_ANSWERS)}}, ["topic"]),
            get_curated_answer,
            status=("finding_answer", "Finding the answer"),
        ),
        ServerTool(
            KB_SEARCH_TOOL,
            f"Search {DOCS_DESCRIPTION} Returns document chunks with titles.",
            schema({"query": {"type": "string", "description": "What to look up"}}, ["query"]),
            search_docs,
            status=SEARCHING_DOCUMENTS,
        ),
        ServerTool(
            PARTS_SEARCH_TOOL,
            f"Search {PARTS_DESCRIPTION} Returns catalog chunks with titles.",
            schema(
                {
                    "query": {
                        "type": "string",
                        "description": "The parts to find, with the model, the drive when "
                        "known, and the position such as front left",
                    }
                },
                ["query"],
            ),
            search_parts,
            status=SEARCHING_PARTS,
        ),
        ServerTool(
            "check_stock",
            "Check how many Voltrieve cars of a model are in stock in a city. Both filters "
            "are optional.",
            schema({"model": MODEL_PROPERTY, "city": CITY_PROPERTY}),
            check_stock,
            status=("checking_stock", "Checking stock"),
        ),
        ServerTool(
            "check_part_stock",
            "Check how many of a spare part each Voltrieve dealer has in stock. Find the article "
            "number with search_spare_parts first. With the city the user named, that city comes "
            "first and the other dealers follow, closest first, with their distance from it.",
            schema(
                {
                    "article": {"type": "string", "pattern": "^VP-\\d{5}$",
                                "description": "Spare part article number, such as VP-10007"},
                    "city": CITY_PROPERTY,
                },
                ["article"],
            ),
            check_part_stock,
            status=("checking_part_stock", "Checking parts stock"),
        ),
        ServerTool(
            "get_prices",
            "Get the dealer's base price per model for a market. It has no drive "
            "configuration prices (such as AWD): those are in the documents.",
            schema({"market": {"type": "string", "enum": ["SE", "EU"]}}),
            get_prices,
            status=("checking_prices", "Checking prices"),
        ),
        ServerTool(
            "get_current_date",
            "Get today's date as YYYY-MM-DD, for working out dates such as next Saturday.",
            schema({}),
            get_current_date,
        ),
        ServerTool(
            "book_test_drive",
            "Book a test drive for the signed-in user. The date must be in the future "
            "(YYYY-MM-DD).",
            schema(
                {
                    "model": MODEL_PROPERTY,
                    "city": CITY_PROPERTY,
                    "date": {"type": "string", "format": "date"},
                },
                ["model", "city", "date"],
            ),
            book_test_drive,
            required_role=BOOK_ROLE,
            status=("booking_test_drive", "Booking your test drive"),
            concurrent=False,  # it changes something, so it never races another tool
        ),
    ]
