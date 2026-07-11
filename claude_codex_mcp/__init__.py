"""Context-OS MCP Server - Exposes the memory system via Model Context Protocol.

Provides memory, experience, knowledge graph, and journal tools
that can be used by MCP clients like Claude Code and Trae IDE.
"""

from claude_codex_mcp.server import create_server, main

__all__ = ["create_server", "main"]
