from __future__ import annotations

from ._shared import logger


def register(ctx, *, api) -> None:
    logger.info("Registering BeU memory plugin")
    ctx.register_tool(
        name="ledger_list",
        toolset="memory",
        schema={
            "name": "ledger_list",
            "description": "Browse recent ledger entries from runtime history with provenance-aware metadata. Use this to list or skim entries, not to search by content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thread_id": {"type": "string"},
                    "kind": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
        handler=api.ledger_list_handler,
        description="Browse recent ledger entries from runtime history with provenance-aware metadata. Use this to list or skim entries, not to search by content.",
    )
    ctx.register_tool(
        name="ledger_search",
        toolset="memory",
        schema={
            "name": "ledger_search",
            "description": "Search ledger entries by meaning and keywords across runtime history, then return matching ledger entries with provenance-aware metadata.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "thread_id": {"type": "string"},
                    "kind": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1},
                },
                "required": ["query"],
            },
        },
        handler=api.ledger_search_handler,
        description="Search ledger entries by meaning and keywords across runtime history, then return matching ledger entries with provenance-aware metadata.",
    )
    ctx.register_tool(
        name="ledger_get",
        toolset="memory",
        schema={
            "name": "ledger_get",
            "description": "Fetch one ledger entry with full content, provenance, and citation metadata.",
            "parameters": {
                "type": "object",
                "properties": {"entry_id": {"type": "string"}},
                "required": ["entry_id"],
            },
        },
        handler=api.ledger_get_handler,
        description="Fetch one ledger entry with full content, provenance, and citation metadata.",
    )
    ctx.register_hook("pre_llm_call", api.pre_llm_call_hook)
    ctx.register_hook("post_llm_call", api.post_llm_call_hook)
    ctx.register_hook("post_tool_call", api.post_tool_call_hook)
    ctx.register_hook("on_session_start", api.on_session_start_hook)
    ctx.register_hook("on_session_end", api.on_session_end_hook)
    logger.info("BeU memory plugin registered successfully")

