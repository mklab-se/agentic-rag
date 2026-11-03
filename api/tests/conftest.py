import os

os.environ.setdefault("TENANT_ID", "00000000-0000-0000-0000-0000000000aa")
os.environ.setdefault("API_CLIENT_ID", "00000000-0000-0000-0000-0000000000cc")

import time  # noqa: E402

import httpx  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from voltrieve_agent.events import AgentEvent, trace  # noqa: E402
from voltrieve_agent.loop import TurnOutcome  # noqa: E402

from app.auth import TokenValidator  # noqa: E402
from app.backends import BackendRegistry  # noqa: E402
from app.main import create_app  # noqa: E402
from app.settings import Settings  # noqa: E402
from app.turns import TurnStore  # noqa: E402


@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def jwks(rsa_key):
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(rsa_key.public_key(), as_dict=True)
    jwk.update({"kid": "test", "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


@pytest.fixture
def make_token(rsa_key):
    def _make(**overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": f"https://login.microsoftonline.com/{os.environ['TENANT_ID']}/v2.0",
            "aud": overrides.get("aud", os.environ["API_CLIENT_ID"]),
            "scp": overrides.get("scp", "access_as_user"),
            "roles": overrides.get("roles", ["Chat.User"]),
            "oid": overrides.get("oid", "oid-anna"),
            "preferred_username": "anna@example.com",
            "azp": "cli",
            "nbf": now - 10,
            "exp": now + overrides.get("exp_delta_seconds", 300),
        }
        return jwt.encode(
            claims, rsa_key, algorithm="RS256", headers={"kid": overrides.get("kid", "test")}
        )

    return _make


@pytest.fixture
def validator(jwks) -> TokenValidator:
    return TokenValidator(
        os.environ["TENANT_ID"], os.environ["API_CLIENT_ID"], jwks_fetcher=lambda: jwks
    )


class FakeBackend:
    """Scripted backend. `script` entries are callables (ctx, emit) -> TurnOutcome."""

    def __init__(self):
        self.script = []
        self.contexts = []
        self.abandoned = []
        self.owners = {}  # conversation id -> owner oid, the "Foundry" side
        self.repaired = []
        self.repair_error = None
        self.abandon_error = None
        self.closed = False
        self.created = 0

    async def create_conversation(self, owner_oid: str) -> str:
        self.created += 1
        self.owners[f"conv_{self.created}"] = owner_oid
        return f"conv_{self.created}"

    async def get_conversation_owner(self, conversation_id):
        return self.owners.get(conversation_id)

    async def run_turn(self, ctx, emit):
        self.contexts.append(ctx)
        return await self.script.pop(0)(ctx, emit)

    async def abandon(self, conversation_id, outputs):
        if self.abandon_error:
            raise self.abandon_error
        self.abandoned.append((conversation_id, outputs))

    async def repair(self, conversation_id):
        if self.repair_error:
            raise self.repair_error
        self.repaired.append(conversation_id)

    async def close(self):
        self.closed = True


def answer(text="Hi", usage=None):
    async def run(ctx, emit):
        await emit(trace("model_called", "model", "iteration 1"))
        await emit(AgentEvent("delta", {"text": text}))
        return TurnOutcome("done", [], usage or {"total_tokens": 5})

    return run


def pause(call_ids=("call_1",), pending=None, usage=None):
    async def run(ctx, emit):
        await emit(
            AgentEvent(
                "client_tool_calls",
                {
                    "turn_id": ctx.turn_id,
                    "calls": [{"call_id": c, "name": "read_file", "arguments": "{}"} for c in call_ids],
                },
            )
        )
        return TurnOutcome("paused", pending or [], usage or {}, list(call_ids))

    return run


@pytest.fixture
def backend():
    return FakeBackend()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def app(validator, backend, clock):
    settings = Settings(cors_origins="http://localhost:5173")
    registry = BackendRegistry(settings, {"loop": lambda s: backend})
    return create_app(settings, validator, registry, TurnStore(clock=clock))


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def auth(make_token):
    return {"Authorization": f"Bearer {make_token()}"}


def parse_sse(text: str) -> list[tuple[str, dict]]:
    import json

    events = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        assert lines[0].startswith("event: ") and lines[1].startswith("data: "), block
        events.append((lines[0][7:], json.loads(lines[1][6:])))
    return events
