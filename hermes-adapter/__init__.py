#!/usr/bin/env python3
"""
BeU Hermes Plugin Adapter
=========================

A Hermes plugin that provides identity persistence and long-term memory
by wrapping the BeU (Become Unfurl) Rust binary.

Commands exposed:
- ledger_list: Browse recent ledger entries
- ledger_search: Search ledger entries by meaning/keywords
- ledger_get: Fetch one ledger entry

Hooks:
- pre_llm_call: Inject identity/invariants into prompt
- post_llm_call: Trigger distillation after LLM response
- on_session_start: Initialize session state
- on_session_end: Flush any pending state
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

logger = logging.getLogger(__name__)

# Path to the BeU binary (can be overridden via BEU_BINARY_PATH)
DEFAULT_BEU_BINARY = "beu"

# Hermes home directory
HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))

# Default namespace for single-agent Hermes (no multi-agent support)
DEFAULT_NAMESPACE = "default"


class BeuProcess:
    """Manages the BeU binary subprocess and communication."""

    _instance: Optional["BeuProcess"] = None
    _lock = threading.Lock()

    def __init__(self, binary_path: Optional[str] = None):
        self.binary_path = (
            binary_path or os.environ.get("BEU_BINARY_PATH") or DEFAULT_BEU_BINARY
        )
        self.process: Optional[subprocess.Popen] = None
        self._ensure_binary()

    def _ensure_binary(self) -> None:
        """Check that the binary exists and is executable."""
        path = Path(self.binary_path)
        if path.exists() and os.access(path, os.X_OK):
            return
        # Try to find in PATH
        try:
            result = subprocess.run(
                ["which", self.binary_path],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                self.binary_path = result.stdout.strip()
                return
        except Exception:
            pass
        raise RuntimeError(f"BeU binary not found at: {self.binary_path}")

    def call(
        self, command: str, payload: dict, namespace: str = DEFAULT_NAMESPACE
    ) -> dict:
        """Send a command to the BeU binary and return the response."""
        request = {
            "version": "1.0.0",
            "command": command,
            "id": f"{command}-{os.urandom(4).hex()}",
            "namespace": namespace,
            "payload": payload,
        }

        try:
            proc = subprocess.run(
                [self.binary_path],
                input=json.dumps(request) + "\n",
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            if proc.returncode != 0:
                logger.error(f"BeU process error: {proc.stderr}")
                return {
                    "ok": False,
                    "error": proc.stderr or "Process exited with non-zero status",
                }

            # Parse the JSON response
            response = json.loads(proc.stdout.strip())
            return response

        except subprocess.TimeoutExpired:
            logger.error("BeU command timed out")
            return {"ok": False, "error": "Command timed out"}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse BeU response: {e}")
            return {"ok": False, "error": f"Invalid JSON response: {e}"}
        except Exception as e:
            logger.error(f"BeU command failed: {e}")
            return {"ok": False, "error": str(e)}

    def distill(
        self,
        thread_id: str,
        turn_id: str,
        thread_history: list,
        namespace: str = DEFAULT_NAMESPACE,
        prior_wake_pack: Optional[dict] = None,
        active_invariants: Optional[list] = None,
    ) -> dict:
        """Compress thread history into memory artifacts."""
        payload = {
            "thread_id": thread_id,
            "turn_id": turn_id,
            "thread_history": thread_history,
            "prior_wake_pack": prior_wake_pack or {},
            "active_invariants": active_invariants or [],
        }

        response = self.call("distill", payload, namespace)

        if response.get("ok"):
            return response.get("data", {})
        else:
            logger.warning(f"Distill failed: {response.get('error')}")
            return {}

    def identity(
        self,
        query: str = "all",
        namespace: str = DEFAULT_NAMESPACE,
        limit: int = 10,
    ) -> dict:
        """Query agent identity state."""
        payload = {
            "query": query,
            "limit": limit,
        }

        response = self.call("identity", payload, namespace)

        if response.get("ok"):
            return response.get("data", {})
        else:
            logger.warning(f"Identity query failed: {response.get('error')}")
            return {}

    def status(self, namespace: str = DEFAULT_NAMESPACE) -> dict:
        """Check the memory plugin status."""
        payload = {}
        response = self.call("status", payload, namespace)

        if response.get("ok"):
            return response.get("data", {})
        else:
            logger.warning(f"Status check failed: {response.get('error')}")
            return {"storage": "error"}


def get_beu() -> BeuProcess:
    """Get or create the singleton BeU process instance."""
    with BeuProcess._lock:
        if BeuProcess._instance is None:
            BeuProcess._instance = BeuProcess()
        return BeuProcess._instance


# -------------------------------------------------------------------------------
# Tool handlers
# -------------------------------------------------------------------------------


def ledger_list_handler(args: dict, **kw) -> str:
    namespace = _resolve_namespace(kw)
    beu = get_beu()
    try:
        result = beu.call(
            "ledger_list",
            {
                "namespace": namespace,
                "thread_id": args.get("thread_id"),
                "kind": args.get("kind"),
                "limit": int(args.get("limit", 20) or 20),
            },
        )
        return json.dumps(result.get("data", {}), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def ledger_search_handler(args: dict, **kw) -> str:
    namespace = _resolve_namespace(kw)
    beu = get_beu()
    query = args.get("query", "")
    if not query:
        return json.dumps({"error": "query is required"})
    try:
        result = beu.call(
            "ledger_search",
            {
                "namespace": namespace,
                "query": query,
                "thread_id": args.get("thread_id"),
                "kind": args.get("kind"),
                "limit": int(args.get("limit", 8) or 8),
            },
        )
        return json.dumps(result.get("data", {}), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def ledger_get_handler(args: dict, **kw) -> str:
    namespace = _resolve_namespace(kw)
    beu = get_beu()
    entry_id = args.get("entry_id", "")
    if not entry_id:
        return json.dumps({"error": "entry_id is required"})
    try:
        result = beu.call(
            "ledger_get",
            {
                "namespace": namespace,
                "entry_id": entry_id,
            },
        )
        if not result.get("ok"):
            return json.dumps({"error": result.get("error", f"ledger entry not found: {entry_id}")})
        return json.dumps(result.get("data", {}), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def beu_distill_handler(args: dict, **kw) -> str:
    """Handle the beu_distill tool call."""
    beu = get_beu()

    thread_id = args.get("thread_id", "")
    turn_id = args.get("turn_id", "")
    namespace = args.get("namespace", DEFAULT_NAMESPACE)

    if not thread_id or not turn_id:
        return json.dumps(
            {"success": False, "error": "thread_id and turn_id are required"}
        )

    # Thread history would typically come from the session context
    # For now, we require it to be passed in
    thread_history = args.get("thread_history", [])

    result = beu.distill(
        thread_id=thread_id,
        turn_id=turn_id,
        thread_history=thread_history,
        namespace=namespace,
    )

    if not result:
        return json.dumps({"success": False, "error": "Distillation failed"})

    return json.dumps(
        {
            "success": True,
            "wake_pack": result.get("wake_pack", {}),
            "facts": result.get("facts", []),
            "invariants": result.get("invariant_adds", []),
        },
        ensure_ascii=False,
    )


# -------------------------------------------------------------------------------
# Hook handlers
# -------------------------------------------------------------------------------


def _resolve_namespace(kwargs: dict) -> str:
    return (
        kwargs.get("session_key")
        or kwargs.get("session_id")
        or kwargs.get("task_id")
        or DEFAULT_NAMESPACE
    )


def _index_entry(
    *,
    namespace: str,
    thread_id: str,
    entry_id: str,
    source_type: str,
    source_id: str,
    content: str,
    metadata: dict,
) -> None:
    text = content.strip()
    if not text:
        return
    beu = get_beu()
    payload = {
        "namespace": namespace,
        "entries": [
            {
                "entry_id": entry_id,
                "source_type": source_type,
                "source_id": str(metadata.get("tool_call_id") or metadata.get("run_id") or entry_id),
                "content": text[:2000],
                "metadata": {
                    **metadata,
                    "thread_id": thread_id,
                },
            }
        ],
    }
    result = beu.call("index", payload)
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "index failed"))


def pre_llm_call_hook(messages: list, **kwargs) -> Optional[str]:
    """Hook that runs before each LLM call.

    Injects identity/invariants into the system prompt or returns
    context to be appended to the prompt.
    """
    namespace = _resolve_namespace(kwargs)

    user_message = kwargs.get("user_message", "")
    if user_message:
        _index_entry(
            namespace=namespace,
            thread_id=str(kwargs.get("session_id") or namespace),
            entry_id=f"{kwargs.get('session_id', namespace)}:{kwargs.get('model', 'llm')}:user",
            source_type="ledger_entry",
            source_id=str(kwargs.get("session_id") or namespace),
            content=str(user_message),
            metadata={
                "kind": "user_turn",
                "session_id": kwargs.get("session_id"),
                "model": kwargs.get("model"),
                "platform": kwargs.get("platform"),
            },
        )

    try:
        return None

    except Exception as e:
        logger.warning(f"pre_llm_call hook failed: {e}")
        return None


def post_llm_call_hook(response: str, messages: list, **kwargs) -> Optional[dict]:
    """Hook that runs after each LLM call.

    Could trigger distillation if configured. For now, this is a
    no-op since distillation requires explicit triggering.
    """
    namespace = _resolve_namespace(kwargs)
    assistant_response = kwargs.get("assistant_response") or response
    if assistant_response:
        _index_entry(
            namespace=namespace,
            thread_id=str(kwargs.get("session_id") or namespace),
            entry_id=f"{kwargs.get('session_id', namespace)}:{kwargs.get('model', 'llm')}:assistant",
            source_type="ledger_entry",
            source_id=str(kwargs.get("session_id") or namespace),
            content=str(assistant_response),
            metadata={
                "kind": "agent_turn",
                "session_id": kwargs.get("session_id"),
                "model": kwargs.get("model"),
                "platform": kwargs.get("platform"),
            },
        )
    return None


def post_tool_call_hook(tool_name: str, args: dict, result: Any, task_id: str, **kwargs) -> None:
    namespace = _resolve_namespace(kwargs)
    _index_entry(
        namespace=namespace,
        thread_id=str(kwargs.get("session_id") or task_id or namespace),
        entry_id=f"{task_id}:{tool_name}:tool",
        source_type="ledger_entry",
        source_id=str(kwargs.get("tool_call_id") or tool_name),
        content=result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
        metadata={
            "kind": "tool_result",
            "tool_name": tool_name,
            "task_id": task_id,
            "tool_call_id": kwargs.get("tool_call_id"),
        },
    )


def on_session_start_hook(**kwargs) -> None:
    """Hook that runs when a new session starts."""
    try:
        logger.info("BeU memory initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize BeU: {e}")


def on_session_end_hook(**kwargs) -> None:
    """Hook that runs when a session ends."""
    # No cleanup needed - BeU is stateless between calls
    pass


# -------------------------------------------------------------------------------
# Plugin registration
# -------------------------------------------------------------------------------


def register(ctx) -> None:
    """Register the BeU plugin with Hermes.

    This function is called by the plugin system when the plugin is loaded.
    It registers tools and hooks with the Hermes plugin context.
    """
    logger.info("Registering BeU memory plugin")

    # Register ledger tools
    ctx.register_tool(
        name="ledger_list",
        toolset="memory",
        schema={
            "name": "ledger_list",
            "description": "Browse recent ledger entries from runtime history with provenance-aware metadata. Use this to list or skim entries, not to search by content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thread_id": {
                        "type": "string",
                    },
                    "kind": {
                        "type": "string",
                    },
                    "limit": {
                        "type": "integer",
                    },
                },
            },
        },
        handler=ledger_list_handler,
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
                    "query": {
                        "type": "string",
                    },
                    "thread_id": {
                        "type": "string",
                    },
                    "kind": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1},
                },
                "required": ["query"],
            },
        },
        handler=ledger_search_handler,
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
                "properties": {
                    "entry_id": {"type": "string"},
                },
                "required": ["entry_id"],
            },
        },
        handler=ledger_get_handler,
        description="Fetch one ledger entry with full content, provenance, and citation metadata.",
    )

    # Register lifecycle hooks
    ctx.register_hook("pre_llm_call", pre_llm_call_hook)
    ctx.register_hook("post_llm_call", post_llm_call_hook)
    ctx.register_hook("post_tool_call", post_tool_call_hook)
    ctx.register_hook("on_session_start", on_session_start_hook)
    ctx.register_hook("on_session_end", on_session_end_hook)

    logger.info("BeU memory plugin registered successfully")
