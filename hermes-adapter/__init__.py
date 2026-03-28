#!/usr/bin/env python3
"""
BeU Hermes Plugin Adapter
=========================

A Hermes plugin that provides identity persistence and long-term memory
by wrapping the BeU (Become Unfurl) Rust binary.

Commands exposed:
- beu_recall: Search memory for relevant context
- beu_distill: Compress turn history into memory artifacts

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

    def recall(
        self,
        query: str,
        namespace: str = DEFAULT_NAMESPACE,
        limit: int = 5,
        sources: Optional[list] = None,
    ) -> list:
        """Search memory for relevant information."""
        payload = {
            "query": query,
            "limit": limit,
            "sources": sources or ["invariant", "fact", "wake_pack"],
        }

        response = self.call("recall", payload, namespace)

        if response.get("ok"):
            return response.get("data", {}).get("hits", [])
        else:
            logger.warning(f"Recall failed: {response.get('error')}")
            return []

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


def beu_recall_handler(args: dict, **kw) -> str:
    """Handle the beu_recall tool call."""
    beu = get_beu()

    query = args.get("query", "")
    namespace = args.get("namespace", DEFAULT_NAMESPACE)
    limit = args.get("limit", 5)
    sources = args.get("sources")

    if not query:
        return json.dumps({"success": False, "error": "Query is required"})

    hits = beu.recall(query=query, namespace=namespace, limit=limit, sources=sources)

    if not hits:
        return json.dumps(
            {
                "success": True,
                "message": "No relevant memories found",
                "hits": [],
            }
        )

    formatted_hits = []
    for hit in hits:
        formatted_hits.append(
            {
                "type": hit.get("source_type", "unknown"),
                "id": hit.get("source_id", ""),
                "content": hit.get("content", "")[:500],  # Truncate long content
                "score": round(hit.get("score", 0.0), 2),
                "citation": hit.get("citation", ""),
            }
        )

    return json.dumps(
        {
            "success": True,
            "hits": formatted_hits,
        },
        ensure_ascii=False,
    )


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


def pre_llm_call_hook(messages: list, **kwargs) -> Optional[str]:
    """Hook that runs before each LLM call.

    Injects identity/invariants into the system prompt or returns
    context to be appended to the prompt.
    """
    beu = get_beu()

    try:
        identity = beu.identity(query="all")

        invariants = identity.get("invariants", [])
        if not invariants:
            return None

        # Format active invariants as a context snippet
        active = [inv for inv in invariants if inv.get("status") == "active"]
        if not active:
            return None

        lines = ["# User Preferences & Identity"]
        for inv in active[:5]:  # Limit to top 5
            lines.append(f"- {inv.get('claim', 'Unknown')}")

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"pre_llm_call hook failed: {e}")
        return None


def post_llm_call_hook(response: str, messages: list, **kwargs) -> Optional[dict]:
    """Hook that runs after each LLM call.

    Could trigger distillation if configured. For now, this is a
    no-op since distillation requires explicit triggering.
    """
    # In a full implementation, this would:
    # 1. Track turn completion
    # 2. Trigger distillation on context flush
    # 3. Store results
    pass
    return None


def on_session_start_hook(**kwargs) -> None:
    """Hook that runs when a new session starts."""
    beu = get_beu()

    try:
        status = beu.status()
        logger.info(f"BeU memory initialized: {status.get('storage', 'unknown')}")
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

    # Register the recall tool
    ctx.register_tool(
        name="beu_recall",
        toolset="memory",
        schema={
            "name": "beu_recall",
            "description": "Search long-term memory for relevant context, facts, and user preferences. Use this proactively when the user references past conversations or you need to recall specific information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query describing what to recall",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 5)",
                        "default": 5,
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Sources to search: invariant, fact, wake_pack",
                        "default": ["invariant", "fact", "wake_pack"],
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Agent namespace (default: default)",
                        "default": "default",
                    },
                },
                "required": ["query"],
            },
        },
        handler=beu_recall_handler,
        description="Search long-term memory",
        emoji="🧠",
    )

    # Register the distill tool (for manual triggering)
    ctx.register_tool(
        name="beu_distill",
        toolset="memory",
        schema={
            "name": "beu_distill",
            "description": "Compress the current conversation into memory artifacts. Extracts facts, invariants, and creates a summary (wake_pack). Typically called automatically on context flush.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thread_id": {
                        "type": "string",
                        "description": "Unique thread/conversation identifier",
                    },
                    "turn_id": {
                        "type": "string",
                        "description": "Current turn identifier",
                    },
                    "thread_history": {
                        "type": "array",
                        "description": "Array of turn events to compress",
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Agent namespace (default: default)",
                        "default": "default",
                    },
                },
                "required": ["thread_id", "turn_id"],
            },
        },
        handler=beu_distill_handler,
        description="Compress conversation to memory",
        emoji="🫧",
    )

    # Register lifecycle hooks
    ctx.register_hook("pre_llm_call", pre_llm_call_hook)
    ctx.register_hook("post_llm_call", post_llm_call_hook)
    ctx.register_hook("on_session_start", on_session_start_hook)
    ctx.register_hook("on_session_end", on_session_end_hook)

    logger.info("BeU memory plugin registered successfully")
