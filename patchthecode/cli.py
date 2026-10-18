"""PatchTheCode CLI: vertical-slice entry point.

Currently supports:
  - `inspect-mcp`: list what tools your configured MCP servers expose and how
    each aligns to the tool maps PatchTheCode expects (great for learning the
    real Coralogix / GitHub / Sentry tool names and aligning your server).
  - `replay`: feed a saved incident JSON through the investigation loop.
  - `demo`: run the pipeline against a synthetic incident (no MCP servers).
  - `poll-prs`: record merged/closed outcomes for open pull requests.
  - `watch`: keep running, pick up incident JSON files from an inbox
    directory (and optionally accept pushed incidents over HTTP
    `POST /incidents`), and investigate each one without a CLI call.
  - `list-prs`: show the open pull requests awaiting review.
  - `rejections`: show fixes reviewers rejected (the learning queue).
  - `status`: operating totals from the store.
  - `playbooks`: list the debugging playbooks for recurring fingerprints.
  - `playbook <fingerprint>`: show one fingerprint's full debugging playbook.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.pretty import pprint

from patchthecode.agent.issues import McpIssueFeed, default_action_for
from patchthecode.agent.orchestrator import Agent
from patchthecode.agent.sources import CompositeFeed, FileInbox, IncidentFeed, QueueFeed
from patchthecode.agent.watch import WatchLoop
from patchthecode.agent.webhook import IncidentWebhook
from patchthecode.config import Settings
from patchthecode.domain import Severity
from patchthecode.domain.models import Incident, IncidentSource, InvestigationReport
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
        settings=settings,
    )


def _issues_feed(settings: Settings, connectors: dict) -> IncidentFeed | None:
    """Wrap an observability connector's facade as an issue feed, if configured."""
    name = settings.issues_connector
    if not name:
        return None
    client = connectors.get(name)
    if client is None:
        console.print(f"[yellow]No connector named {name!r}; --issues feed disabled.[/yellow]")
        return None
    connection = getattr(client, "connection", None)
    if connection is None:
        console.print(f"[yellow]No connection on {name!r}; --issues feed disabled.[/yellow]")
        return None
    try:
        facade = adapter_for(connection, client)
    except Exception:  # noqa: BLE001 - a misconfigured connector just gets no feed
        console.print(f"[yellow]Could not build an adapter for {name!r}; --issues feed disabled.[/yellow]")
        return None
    action = settings.issues_action or None
    arguments: dict = {}
    if action in (None, "query_logs"):
        from datetime import datetime, timedelta

        now = datetime.utcnow()
        arguments.setdefault(
            "time_range",
            {"from": (now - timedelta(hours=1)).isoformat(), "to": now.isoformat()},
        )
    if settings.issues_query:
        arguments.setdefault("query", settings.issues_query)
    console.print(
        f"[cyan]Issues feed: {name} ({getattr(facade, 'system', '?')}"
        f"/{action or default_action_for(facade)}) query={settings.issues_query!r}[/cyan]"
    )
    return McpIssueFeed(facade, action=action, arguments=arguments)


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
def watch(
    inbox: Annotated[
        Path | None,
        typer.Option("--inbox", help="Directory watched for incident JSON files"),
    ] = None,
    interval: Annotated[
        int | None,
        typer.Option("--interval", help="Seconds between polls"),
    ] = None,
    once: Annotated[
        bool, typer.Option("--once", help="Run a single cycle and exit")
    ] = False,
    cycles: Annotated[
        int | None, typer.Option("--cycles", help="Stop after N cycles (default: run until Ctrl-C)")
    ] = None,
    no_pr_poll: Annotated[
        bool, typer.Option("--no-pr-poll", help="Do not refresh pull-request outcomes each cycle")
    ] = False,
    webhook_port: Annotated[
        int | None,
        typer.Option(
            "--webhook-port",
            help="Also accept pushed incidents via HTTP POST /incidents on this port (0 = random)",
        ),
    ] = None,
    issues: Annotated[
        str | None,
        typer.Option(
            "--issues",
            help="Observability connector name to poll for new issues (e.g. sentry_mcp)",
        ),
    ] = None,
    issues_query: Annotated[
        str | None,
        typer.Option("--issues-query", help="Query/filter for the issues feed (default is:unresolved)"),
    ] = None,
) -> None:
    """Watch an incident inbox and investigate new incidents automatically."""
    settings = _settings()
    if issues is not None:
        settings.issues_connector = issues
    if issues_query is not None:
        settings.issues_query = issues_query
    inbox_dir = inbox or settings.watch_inbox
    interval_seconds = interval if interval is not None else settings.watch_interval_seconds
    max_cycles = 1 if once else cycles
    agent = _build_agent(settings)
    inbox_feed = FileInbox(inbox_dir)
    queue = QueueFeed()
    webhook = IncidentWebhook(queue, port=webhook_port) if webhook_port is not None else None
    issue_feed = _issues_feed(settings, getattr(agent, "connectors", {}) or {})
    feeds: list[IncidentFeed] = [inbox_feed]
    if webhook is not None:
        feeds.append(queue)
    if issue_feed is not None:
        feeds.append(issue_feed)
    feed: IncidentFeed = CompositeFeed(feeds) if len(feeds) > 1 else inbox_feed
    console.print(
        f"[cyan]Watching {inbox_dir} every {interval_seconds}s"
        + (" (single cycle)" if max_cycles == 1 else "")
        + ". Drop incident JSON files there; Ctrl-C to stop.[/cyan]"
    )

    def _on_cycle(cycle: int) -> None:
        console.print(f"[dim]cycle {cycle}[/dim]")

    def _on_report(report: InvestigationReport) -> None:
        console.print(
            f"  {report.incident.id} [{report.incident.fingerprint}] -> [green]{report.status}[/green]"
        )

    loop = WatchLoop(
        agent=agent,
        feed=feed,
        interval_seconds=interval_seconds,
        max_cycles=max_cycles,
        poll_pull_requests=not no_pr_poll,
        on_cycle=_on_cycle,
        on_report=_on_report,
    )

    async def _run() -> list[InvestigationReport]:
        if webhook is not None:
            port = await webhook.start()
            console.print(f"[cyan]Webhook: POST http://{webhook.host}:{port}/incidents[/cyan]")
        try:
            return await loop.run()
        finally:
            if webhook is not None:
                await webhook.stop()

    try:
        reports = asyncio.run(_run())
    except KeyboardInterrupt:  # pragma: no cover - interactive stop
        console.print("[yellow]Watch stopped.[/yellow]")
        return
    if reports:
        by_status: dict[str, int] = {}
        for report in reports:
            by_status[report.status] = by_status.get(report.status, 0) + 1
        summary = ", ".join(f"{status}={count}" for status, count in sorted(by_status.items()))
        console.print(f"[green]Watch finished {len(reports)} investigation(s): {summary}[/green]")
    else:
        console.print("[yellow]No new incidents found.[/yellow]")


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


@app.command()
def playbooks() -> None:
    """List the debugging playbooks for recurring fingerprints."""
    agent = _build_agent(_settings())
    books = agent.store.playbooks()
    if not books:
        console.print("[yellow]No playbooks yet.[/yellow]")
        return
    for book in books:
        merged = "merged" if book["merged"] else "no accepted fix"
        console.print(
            f"  {book['fingerprint']} recurrences={book['recurrences']} "
            f"{merged} rejections={len(book['rejections'])}"
        )
        if book["last_title"]:
            console.print(f"      {book['last_title']}")


@app.command()
def playbook(fingerprint: Annotated[str, typer.Argument(help="incident fingerprint")]) -> None:
    """Show one fingerprint's debugging playbook."""
    agent = _build_agent(_settings())
    book = agent.store.playbook(fingerprint)
    if book is None:
        console.print(f"[yellow]No playbook for {fingerprint}.[/yellow]")
        return
    console.print(f"  fingerprint: {book['fingerprint']}")
    console.print(f"  recurrences: [cyan]{book['recurrences']}[/cyan]")
    console.print(f"  first_seen:  {book['first_seen']}")
    console.print(f"  last_seen:   {book['last_seen']}")
    if book["last_title"]:
        console.print(f"  last title:  {book['last_title']}")
    merged = book["merged"]
    if merged:
        console.print(f"  accepted fix ({merged['pr']}): {merged['summary']}")
    for rejected in book["rejections"]:
        console.print(f"  rejected ({rejected['reason']}): {rejected['summary']}")


if __name__ == "__main__":
    app()