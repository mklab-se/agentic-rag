import json
from typing import Any

from pydantic import BaseModel, Field

from voltrieve_agent.tools import ClientTool

ID_PATTERN = r"^[A-Za-z0-9._-]{1,128}$"
MAX_CLIENT_TOOLS = 16
MAX_CLIENT_TOOLS_BYTES = 16 * 1024


class ClientToolModel(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_]{1,64}$")
    description: str = Field(max_length=2000)
    parameters: dict[str, Any]


class ChatRequest(BaseModel):
    conversation_id: str | None = Field(default=None, pattern=ID_PATTERN)
    message: str = Field(min_length=1, max_length=8000)
    client_tools: list[ClientToolModel] = Field(default_factory=list, max_length=MAX_CLIENT_TOOLS)


class ToolResult(BaseModel):
    call_id: str = Field(pattern=ID_PATTERN)
    output: Any = ""

    def output_text(self) -> str:
        return self.output if isinstance(self.output, str) else json.dumps(self.output)


class ToolResultsRequest(BaseModel):
    conversation_id: str = Field(pattern=ID_PATTERN)
    turn_id: str = Field(pattern=ID_PATTERN)
    results: list[ToolResult] = Field(min_length=1, max_length=64)


def to_client_tools(models: list[ClientToolModel]) -> list[ClientTool]:
    return [ClientTool(m.name, m.description, m.parameters) for m in models]
