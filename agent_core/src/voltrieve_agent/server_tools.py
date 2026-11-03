"""Tools the agent runs on the server: documentation search and dealer operations."""

from voltrieve_agent.dealer import DealerClient
from voltrieve_agent.knowledge import KnowledgeBase
from voltrieve_agent.tools import ServerTool, UserContext

BOOK_ROLE = "TestDrive.Book"


def build_server_tools(dealer: DealerClient, search: KnowledgeBase) -> list[ServerTool]:
    async def search_docs(args: dict, user: UserContext) -> str:
        return await search.search(args["query"])

    async def check_stock(args: dict, user: UserContext) -> str:
        return await dealer.stock(args.get("model"), args.get("city"))

    async def get_prices(args: dict, user: UserContext) -> str:
        return await dealer.prices(args.get("market", "SE"))

    async def book_test_drive(args: dict, user: UserContext) -> str:
        # The requester is the signed-in user, never something the model supplies.
        return await dealer.book(args["model"], args["city"], args["date"], user.oid)

    def schema(properties: dict, required: list[str] | None = None) -> dict:
        return {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        }

    return [
        ServerTool(
            "search_voltrieve_docs",
            "Search the Voltrieve documentation (owner manuals, specifications, service "
            "guides). Returns document chunks with titles.",
            schema({"query": {"type": "string", "description": "What to look up"}}, ["query"]),
            search_docs,
        ),
        ServerTool(
            "check_stock",
            "Check how many Voltrieve cars of a model are in stock in a city. Both filters "
            "are optional.",
            schema({"model": {"type": "string"}, "city": {"type": "string"}}),
            check_stock,
        ),
        ServerTool(
            "get_prices",
            "Get the current Voltrieve price list for a market.",
            schema({"market": {"type": "string", "enum": ["SE", "EU"]}}),
            get_prices,
        ),
        ServerTool(
            "book_test_drive",
            "Book a test drive for the signed-in user. The date must be in the future "
            "(YYYY-MM-DD).",
            schema(
                {
                    "model": {"type": "string"},
                    "city": {"type": "string"},
                    "date": {"type": "string", "format": "date"},
                },
                ["model", "city", "date"],
            ),
            book_test_drive,
            required_role=BOOK_ROLE,
        ),
    ]
