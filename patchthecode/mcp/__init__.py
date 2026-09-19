"""MCP integration layer: client, redaction, and connector registry."""

from patchthecode.mcp.client import MCPClient, MCPToolError
from patchthecode.mcp.redaction import Redactor, redact_text
from patchthecode.mcp.registry import ConnectorRegistry

__all__ = ["ConnectorRegistry", "MCPClient", "MCPToolError", "Redactor", "redact_text"]