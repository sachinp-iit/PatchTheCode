"""PatchTheCode CLI: vertical-slice entry point.

Currently supports:
  - `inspect-mcp`: list what tools your configured MCP servers expose and how
    each aligns to the tool maps PatchTheCode expects (great for learning the
    real Coralogix / GitHub / Sentry tool names and aligning your server).
  - `replay`: feed a saved incident JSON through the investigation loop.
  - `demo`: run the pipeline against a synthetic incident (no MCP servers).
  - `poll-prs`: record merged/closed outcomes for open pull requests.
  - `list-prs`: show the open pull requests awaiting review.
  - `rejections`: show fixes reviewers rejected (the learning queue).
  - `status`: operating totals from the store.
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
from patchthecode.integrations.factory import adapter_for, hint_for
from patchthecode.integrations.names import report_for
from patchthecode.llm.gateway import LLMGateway
from patchthecode.mcp.registry import ConnectorRegistry
from patchthecode.notifications.notifier import build_notifiers
from patchthecode.security.approver import ChannelApprover
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
    connectors = _build_connectors(settings)
    return Agent(
        gateway=gateway,
        store=store,
        notifiers=build_notifiers(connectors),
        connectors=connectors,
        auto_pr=settings.auto_pr,
        approver=_channel_approver(settings, connectors),
    )


def _channel_approver(settings: Settings, connectors: dict):
    """An interactive ChannelApprover when a channel is configured (and PRs are not auto-approved)."""
    if settings.auto_pr or not settings.approval_channel:
        return None
    for client in connectors.values():
        connection = getattr(client, "connection", None)
        if connection is None or getattr(connection, "kind", "") != "communication":
            continue
        try:
            facade = adapter_for(connection, client)
        except Exception:  # noqa: BLE001 - a misconfigured connector just gets no approver
            continue
        if getattr(facade, "send_message", None) is not None and getattr(facade, "read_messages", None) is not None:
            console.print(f"[cyan]Approval requests -> {getattr(facade, 'system', 'chat')} {settings.approval_channel}[/cyan]")
            return ChannelApprover(
                facade,
                channel=settings.approval_channel,
                timeout_seconds=settings.approval_timeout_seconds,
            )
    return None


@app.command()
def inspect_mcp(
    dump_to: Annotated[
        Path | None,
        typer.Option(
            "--dump-to",
            help="Write one JSON report per connector into this directory",
        ),
    ] = None,
) -> None:
    """List configured MCP servers' tools and how they align to PatchTheCode's maps."""
    settings = _settings()
    registry = ConnectorRegistry(settings.mcp_connections())
    if not registry.names():
        console.print("[yellow]No MCP servers configured. Set PATCHTHECODE_MCP_CONFIG in .env.[/yellow]")
        return

    async def _inspect() -> None:
        for name in registry.names():
            client = registry.get(name)
            tools = await client.list_tools()
            advertised = [str(tool["name"]) for tool in tools]
            facade = adapter_for(client.connection, client)
            system = getattr(facade, "system", hint_for(client.connection))
            report = report_for(system, advertised)
            console.print(f"\n[bold]{name}[/bold] (kind={client.connection.kind}, system={system})")
            console.print(f"  advertised tools: {', '.join(advertised) or 'none'}")
            for action in report["actions"]:
                marker = "[green]aligned[/green]" if action["status"] == "aligned" else "[yellow]fallback[/yellow]"
                suffix = "[cyan] (override)[/cyan]" if action["override"] else ""
                console.print(
                    f"  {action['action']} -> {action['chosen']} [{marker}]{suffix} | try: {', '.join(action['candidates'])}"
                )
            if dump_to is not None:
                dump_to.mkdir(parents=True, exist_ok=True)
                out = dump_to / f"{name}.json"
                out.write_text(
                    json.dumps({"connector": name, "advertised": advertised, "alignment": report}, indent=2),
                    encoding="utf-8",
                )
                console.print(f"  wrote {out}")

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


@app.command()
def poll_prs() -> None:
    """Poll open pull requests and record merged/closed outcomes in the Store."""
    agent = _build_agent(_settings())
    updates = asyncio.run(agent.poll_pull_requests())
    if not updates:
        console.print("[yellow]No open PRs whose state changed.[/yellow]")
        return
    for update in updates:
        console.print(f"  {update['url']} -> [cyan]{update['state']}[/cyan] (incident {update['incident_id']})")


@app.command()
def list_prs() -> None:
    """List the open pull requests awaiting review."""
    agent = _build_agent(_settings())
    entries = agent.store.open_pull_requests()
    if not entries:
        console.print("[yellow]No open pull requests.[/yellow]")
        return
    for entry in entries:
        pr = entry["pr"]
        console.print(f"  {pr.url} (#{pr.number}) incident={entry['incident_id']} repo={entry['repository']}")


@app.command()
def rejections() -> None:
    """List fixes reviewers rejected, to steer future attempts."""
    agent = _build_agent(_settings())
    rows = agent.store.all_rejections()
    if not rows:
        console.print("[yellow]No rejected fixes recorded.[/yellow]")
        return
    for row in rows:
        summary = row["summary"]
        if len(summary) > 84:
            summary = summary[:81] + "..."
        console.print(
            f"  [{row['created_at']}] incident={row['incident_id']} reason={row['reason']}"
        )
        console.print(f"      fingerprint={row['fingerprint']}")
        console.print(f"      {summary}")


@app.command()
def status() -> None:
    """Operating totals from the store."""
    agent = _build_agent(_settings())
    counts = agent.store.summary()
    for key, value in counts.items():
        console.print(f"  {key}: [cyan]{value}[/cyan]")


if __name__ == "__main__":
    app()