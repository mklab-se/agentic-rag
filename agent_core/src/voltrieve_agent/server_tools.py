"""Tools the agent runs on the server: knowledge base search and dealer operations."""

import datetime
from zoneinfo import ZoneInfo

from voltrieve_agent.dealer import DealerClient
from voltrieve_agent.knowledge import KnowledgeBase
from voltrieve_agent.tools import ServerTool, UserContext

BOOK_ROLE = "TestDrive.Book"
KB_SEARCH_TOOL = "search_voltrieve_docs"
PARTS_SEARCH_TOOL = "search_spare_parts"
# Prompt agents get the knowledge bases as MCP tools instead, so they drop these.
KB_SEARCH_TOOLS = (KB_SEARCH_TOOL, PARTS_SEARCH_TOOL)
# The model routes on these words alone, so each says what its base holds and what it does not.
DOCS_DESCRIPTION = (
    "The Voltrieve product and workshop documents: sales brochures, technical specification "
    "guides, the buyer's guide and the service guide. Use for features, specifications, "
    "prices, option packs and what a repair or service job consists of. It has no article "
    "numbers."
)
PARTS_DESCRIPTION = (
    "The Voltrieve spare parts catalogs: article numbers, part descriptions, positions on the "
    "car and the vehicles each part fits. Use to find a part or an article number. It does not "
    "say which parts a job needs or how to do the work."
)
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

    async def get_prices(args: dict, user: UserContext) -> str:
        return await dealer.prices(args.get("market", "SE"))

    async def book_test_drive(args: dict, user: UserContext) -> str:
        # The requester is the signed-in user, never something the model supplies.
        return await dealer.book(args["model"], args["city"], args["date"], user.oid)

    async def get_current_date(args: dict, user: UserContext) -> str:
        return datetime.datetime.now(DEALER_TIMEZONE).date().isoformat()

    def schema(properties: dict, required: list[str] | None = None) -> dict:
        return {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        }

    return [
        ServerTool(
            KB_SEARCH_TOOL,
            f"Search {DOCS_DESCRIPTION} Returns document chunks with titles.",
            schema({"query": {"type": "string", "description": "What to look up"}}, ["query"]),
            search_docs,
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
        ),
        ServerTool(
            "check_stock",
            "Check how many Voltrieve cars of a model are in stock in a city. Both filters "
            "are optional.",
            schema({"model": MODEL_PROPERTY, "city": CITY_PROPERTY}),
            check_stock,
        ),
        ServerTool(
            "get_prices",
            "Get the dealer's base price per model for a market. It has no drive "
            "configuration prices (such as AWD): those are in the documents.",
            schema({"market": {"type": "string", "enum": ["SE", "EU"]}}),
            get_prices,
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
            concurrent=False,  # it changes something, so it never races another tool
        ),
    ]
