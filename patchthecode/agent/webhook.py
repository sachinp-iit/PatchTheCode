"""HTTP endpoint that accepts incident payloads for the watch loop.

A minimal HTTP/1.1 server (stdlib only) so any alerting system can push work
with a single POST: `POST /incidents` with either a full `Incident` payload or
a minimal alert envelope (`{"title": ..., "service": ..., "severity": ...}`).
Accepted payloads are queued for the next watch cycle and answered with 202.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from patchthecode.agent.sources import QueueFeed
from patchthecode.detection.webhook import InvalidIncidentPayload, incident_from_payload

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1_048_576  # 1 MiB: incident payloads are small; refuse to buffer more
MAX_HEADER_BYTES = 8_192
_REASONS = {200: "OK", 202: "Accepted", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed", 413: "Payload Too Large"}


class IncidentWebhook:
    """Listen for incident JSON and queue it for `WatchLoop`."""

    def __init__(self, feed: QueueFeed, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.feed = feed
        self.host = host
        self.port = port
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> int:
        """Bind and accept connections; returns the actual port."""
        self._server = await asyncio.start_server(
            self._handle, self.host, self.port, limit=MAX_HEADER_BYTES
        )
        bound = self._server.sockets
        if bound:
            self.port = int(bound[0].getsockname()[1])
        logger.info("incident webhook listening on http://%s:%s/incidents", self.host, self.port)
        return self.port

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await self._route(reader, writer)
        except (ConnectionResetError, BrokenPipeError):
            logger.debug("client disconnected before the response was written")
        except Exception:  # noqa: BLE001 - a malformed request never kills the server
            logger.exception("webhook request failed")
            try:
                await self._respond(writer, 400, {"error": "malformed request"})
            except Exception:  # noqa: BLE001 - the peer may already be gone
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: BLE001 - the peer may already be gone
                pass

    async def _route(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            header_bytes = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            await self._respond(writer, 400, {"error": "malformed request headers"})
            return
        lines = header_bytes.decode("latin-1").split("\r\n")
        parts = lines[0].split()
        if len(parts) < 3:
            await self._respond(writer, 400, {"error": "malformed request line"})
            return
        method, path = parts[0].upper(), parts[1]
        if method != "POST":
            await self._respond(writer, 405, {"error": "use POST /incidents"}, extra={"Allow": "POST"})
            return
        if path != "/incidents":
            await self._respond(writer, 404, {"error": "unknown endpoint; use POST /incidents"})
            return

        length = _content_length(lines[1:])
        if length is None:
            await self._respond(writer, 400, {"error": "Content-Length header required"})
            return
        if length > MAX_BODY_BYTES:
            await self._respond(writer, 413, {"error": f"body exceeds {MAX_BODY_BYTES} bytes"})
            return
        try:
            body = await reader.readexactly(length)
        except asyncio.IncompleteReadError:
            await self._respond(writer, 400, {"error": "truncated body"})
            return

        try:
            payload = json.loads(body)
        except ValueError:
            await self._respond(writer, 400, {"error": "body is not valid JSON"})
            return
        try:
            incident = incident_from_payload(payload)
        except InvalidIncidentPayload as exc:
            await self._respond(writer, 400, {"error": str(exc)})
            return
        queued = self.feed.push(incident)
        await self._respond(writer, 202, {"queued": queued, "incident_id": incident.id})
        logger.info("webhook queued incident %s (%s)", incident.id, incident.title)

    async def _respond(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        payload: dict[str, Any],
        extra: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        head = [
            f"HTTP/1.1 {status} {_REASONS.get(status, 'OK')}",
            "Content-Type: application/json",
            f"Content-Length: {len(body)}",
            "Connection: close",
        ]
        if extra:
            head.extend(f"{key}: {value}" for key, value in extra.items())
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode("latin-1") + body)
        await writer.drain()


def _content_length(header_lines: list[str]) -> int | None:
    for line in header_lines:
        name, _, value = line.partition(":")
        if name.strip().lower() == "content-length":
            try:
                return int(value.strip())
            except ValueError:
                return None
    return None
