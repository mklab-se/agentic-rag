"""Typer entry point for the `voltrieve` command."""

from __future__ import annotations

import sys
from enum import Enum
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape

from . import auth
from .api import ApiClient, ApiError, run_turn
from .config import ConfigError, load_settings
from .render import ChatView, json_line

app = typer.Typer(help="Voltrieve terminal client.", no_args_is_help=True)
err = Console(stderr=True)


class Backend(str, Enum):
    prompt = "prompt"
    loop = "loop"
    hosted = "hosted"


BackendOpt = Annotated[Backend | None, typer.Option(help="Agent backend (X-Agent-Backend).")]
AzOpt = Annotated[bool, typer.Option("--az-token", help="Use `az account get-access-token`.")]
DeviceOpt = Annotated[bool, typer.Option("--device-code", help="Device code sign-in.")]


def _fail(message: str) -> typer.Exit:
    err.print(f"[red]{escape(message)}[/red]")
    return typer.Exit(1)


def _client(backend: Backend | None, az_token: bool) -> ApiClient:
    try:
        settings = load_settings()

        def provider() -> str:
            # MSAL refreshes silently from the cache, so long sessions keep a valid token.
            return auth.get_token(settings, az_token=az_token, interactive=False)

        provider()  # fail early with a clear message
    except (ConfigError, auth.AuthError) as exc:
        raise _fail(str(exc))
    return ApiClient(settings.api_url, provider, backend.value if backend else None)


@app.command()
def login(device_code: DeviceOpt = False) -> None:
    """Sign in with Entra and cache the token."""
    try:
        auth.get_token(load_settings(), device_code=device_code)
    except (ConfigError, auth.AuthError) as exc:
        raise _fail(str(exc))
    typer.echo("Signed in.")


@app.command()
def ask(question: str, backend: BackendOpt = None, json_out: Annotated[bool, typer.Option("--json")] = False,
        az_token: AzOpt = False) -> None:
    """Ask one question. With --json, print every event as a JSON line."""
    client = _client(backend, az_token)
    out = Console()
    status = {"ok": True}

    def show(name: str, data: dict[str, Any]) -> None:
        if json_out:
            sys.stdout.write(json_line(name, data) + "\n")
            sys.stdout.flush()
        elif name == "delta":
            out.print(data.get("text", ""), end="", markup=False, highlight=False)
        elif name == "tool_ran":
            err.print(f"[dim]client tool {escape(str(data.get('name')))}: {escape(str(data.get('output')))}[/dim]")
        elif name == "trace":
            err.print(f"[dim]{escape(str(data.get('component')))} {escape(str(data.get('step')))}: {escape(str(data.get('detail')))}[/dim]")
        elif name == "error":
            err.print(f"[red]error {escape(str(data.get('code')))}: {escape(str(data.get('message')))}[/red]")
        if name == "error":
            status["ok"] = False

    try:
        outcome = run_turn(client, question, None, show,
                           banner=lambda t: err.print(f"[bold black on yellow] {escape(t)} [/]"))
    except (ApiError, OSError) as exc:
        raise _fail(str(exc))
    finally:
        client.close()
    if not json_out:
        out.print()
    if outcome.error or not status["ok"]:
        raise typer.Exit(1)


@app.command()
def chat(backend: BackendOpt = None, az_token: AzOpt = False) -> None:
    """Interactive chat with a live trace panel. Empty line or Ctrl-D exits."""
    client = _client(backend, az_token)
    console = Console()
    conversation_id: str | None = None
    try:
        while True:
            try:
                message = console.input("[bold cyan]> [/]").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not message:
                break
            with ChatView(console) as view:
                view.user(message)
                try:
                    outcome = run_turn(client, message, conversation_id, view.on_event,
                                       banner=view.show_banner)
                except (ApiError, OSError) as exc:
                    view.on_event("error", {"code": "client", "message": str(exc)})
                    continue
            conversation_id = outcome.conversation_id or conversation_id
    finally:
        client.close()


if __name__ == "__main__":  # pragma: no cover
    app()
