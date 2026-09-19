"""PatchTheCode CLI: vertical-slice entry point.

Currently supports:
  - `inspect-mcp`: list what tools your configured MCP servers expose (great
    for learning the real Coralogix / GitHub tool names).
  - `replay`: feed a saved incident JSON through the investigation loop.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.pretty import pprint

from patchthecode.agent.orchestrator import Agent
from patchthecode.config import Settings
from patchthecode.domain import Severity
from patchthecode.domain.models import Incident, IncidentSource
from patchthecode.llm.gateway import LLMGateway
from patchthecode.mcp.registry import ConnectorRegistry
from patchthecode.notifications.notifier import build_notifiers
from patchthecode.storage.store import Store

app = typer.Typer(help="PatchTheCode: AI Production Engineer over MCP-connected systems.")
console = Console()


def _settings() -> Settings:
    return Settings()


def _build_connectors(settings: Settings) -> dict:
    registry = ConnectorRegistry(settings.mcp_connections())
    return {c.connection.name: c for c in registry.all()}


def _build_agent(settings: Settings) -> Agent:
    gateway = LLMGateway(settings.model_configs(), timeout_seconds=settings.llm_timeout_seconds)
    store = Store(settings.store_path)
    notifiers = build_notifiers(
        slack_webhook_url=settings.slack_webhook_url,
        teams_webhook_url=settings.teams_webhook_url,
    )
    return Agent(gateway=gateway, store=store, notifiers=notifiers, connectors=_build_connectors(settings))


@app.command()
def inspect_mcp() -> None:
    """List connectors and tools exposed by the configured MCP servers."""
    settings = _settings()
    registry = ConnectorRegistry(settings.mcp_connections())
    if not registry.names():
        console.print("[yellow]No MCP servers configured. Set PATCHTHECODE_MCP_CONFIG in .env.[/yellow]")
        return
    console.print(f"Connectors: {registry.names()}")

    async def _inspect() -> None:
        for name in registry.names():
            client = registry.get(name)
            tools = await client.list_tools()
            for tool in tools:
                console.print(f"  [cyan]{name}[/cyan] -> {tool['name']}: {tool['description']}")

    asyncio.run(_inspect())


@app.command()
def replay(
    incident_file: Annotated[Path, typer.Argument(help="JSON file with an Incident payload")],
) -> None:
    """Replay a saved incident through the investigation pipeline."""
    if not incident_file.exists():
        console.print(f"[red]File not found: {incident_file}[/red]")
        raise typer.Exit(code=1)
    raw = json.loads(incident_file.read_text(encoding="utf-8"))
    incident = Incident.model_validate(raw)
    agent = _build_agent(_settings())
    report = asyncio.run(agent.handle(incident))
    pprint(report.model_dump(mode="json"))


def _sample_incident() -> Incident:
    from datetime import datetime

    ts = datetime.fromisoformat("2026-09-19T10:32:00")
    return Incident(
        id="demo:logs:abc",
        fingerprint="demo-fingerprint",
        source=IncidentSource(kind="logs", system="coralogix"),
        severity=Severity.ERROR,
        title="NullPointerException in PaymentService.processPayment",
        description="Demo incident for local replay",
        first_seen=ts,
        last_seen=ts,
        occurrences=1842,
        raw={"service": "payments-api"},
    )


@app.command()
def demo() -> None:
    """Run the pipeline against a synthetic incident (no MCP servers needed)."""
    incident = _sample_incident()
    agent = _build_agent(_settings())
    report = asyncio.run(agent.handle(incident))
    pprint(report.model_dump(mode="json"))
    console.print("[green]Demo finished. Duplicates now short-circuit via the Store.[/green]")


if __name__ == "__main__":
    app()