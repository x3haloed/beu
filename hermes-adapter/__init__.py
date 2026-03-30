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
import shutil
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
SUPPORTED_EMBEDDING_PROVIDERS = {
    "openai",
    "openrouter",
    "custom",
    "google",
    "mistral",
}


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


def _deep_merge_dicts(base: dict, updates: dict) -> dict:
    """Recursively merge update values into a copy of base."""
    merged = dict(base or {})
    for key, value in (updates or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged.get(key, {}), value)
        else:
            merged[key] = value
    return merged


BEU_CONFIG_ENV = "BEU_CONFIG_PATH"
BEU_EMBEDDING_ENV_KEYS = {
    "provider": "BEU_EMBEDDINGS_PROVIDER",
    "base_url": "BEU_EMBEDDINGS_BASE_URL",
    "api_key": "BEU_EMBEDDINGS_API_KEY",
    "model": "BEU_EMBEDDINGS_MODEL",
}
BEU_DEFAULT_CONFIG_FILENAMES = ("beu.yaml", "beu.yml")


def _beu_config_candidate_paths() -> list[Path]:
    candidate_paths = []
    env_path = os.environ.get(BEU_CONFIG_ENV, "").strip()
    if env_path:
        candidate_paths.append(Path(env_path).expanduser())

    adapter_dir = Path(__file__).resolve().parent
    candidate_paths.extend(adapter_dir / name for name in BEU_DEFAULT_CONFIG_FILENAMES)
    return candidate_paths


def _resolve_beu_config_path(prefer_existing: bool = True) -> Path:
    """Return the active BeU config path.

    If prefer_existing is True, return the first config file that already exists.
    Otherwise return the preferred write location even if it has not been created yet.
    """
    candidate_paths = _beu_config_candidate_paths()
    if prefer_existing:
        for path in candidate_paths:
            if path.is_file():
                return path
    return candidate_paths[0] if candidate_paths else Path(__file__).resolve().parent / "beu.yaml"


def _read_beu_config_data(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("Failed to read BeU config %s: %s", path, exc)
        return {}
    if isinstance(data, dict):
        return data
    logger.warning("BeU config %s must contain a mapping at the top level", path)
    return {}


def _load_beu_config_file() -> dict:
    """Load BeU-local configuration from disk.

    Priority:
    1. BEU_CONFIG_PATH
    2. beu.yaml next to this adapter
    3. beu.yml next to this adapter
    """
    return _read_beu_config_data(_resolve_beu_config_path(prefer_existing=True))


def _collect_beu_embedding_settings() -> dict:
    """Merge BeU-local embeddings config and env overrides."""
    config = _load_beu_config_file()
    embeddings_cfg = {}

    if isinstance(config.get("embeddings"), dict):
        embeddings_cfg.update(config["embeddings"])

    # Convenience top-level keys for simple configs.
    for key in ("provider", "base_url", "api_key", "model"):
        value = config.get(key)
        if value not in (None, "") and key not in embeddings_cfg:
            embeddings_cfg[key] = value

    for key, env_name in BEU_EMBEDDING_ENV_KEYS.items():
        value = os.environ.get(env_name, "").strip()
        if value:
            embeddings_cfg[key] = value

    cleaned = {}
    for key, value in embeddings_cfg.items():
        text_value = str(value or "").strip()
        if text_value:
            cleaned[key] = text_value
    return cleaned


def _resolve_embedding_provider(*, namespace: str, kwargs: dict) -> Optional[dict]:
    """Resolve a provider/config block suitable for BeU embeddings.

    Order of precedence:
    1. BeU-local embeddings config (beu.yaml or BEU_CONFIG_PATH)
    2. Hermes runtime provider resolution

    The BeU-local layer is intentionally separate so Hermes chat/provider
    selection can differ from BeU's embedding provider. When we do fall back to
    Hermes, we delegate to Hermes' runtime provider resolver so its special
    provider handlers (for example Gemini vs. OpenAI-compatible routing) stay
    intact.
    """
    local_settings = _collect_beu_embedding_settings()
    if local_settings:
        provider = str(local_settings.get("provider") or "").strip().lower()
        base_url = str(local_settings.get("base_url") or "").strip().rstrip("/")
        api_key = str(local_settings.get("api_key") or "").strip()
        model = str(local_settings.get("model") or "").strip()

        if not provider and base_url:
            provider = "custom"

        if provider and model:
            embedding_provider = {
                "provider": provider,
                "model": model,
            }
            if base_url:
                embedding_provider["base_url"] = base_url
            if api_key:
                embedding_provider["api_key"] = api_key
            return embedding_provider

        if any(local_settings.values()):
            logger.warning(
                "BeU embeddings config is present but incomplete; falling back to Hermes provider resolution"
            )

    try:
        from hermes_cli.runtime_provider import (
            resolve_requested_provider,
            resolve_runtime_provider,
        )
    except Exception as exc:
        logger.warning(f"Embedding provider resolution unavailable: {exc}")
        return None

    requested = kwargs.get("provider") or resolve_requested_provider()

    try:
        runtime = resolve_runtime_provider(requested=requested)
    except Exception as exc:
        logger.debug(f"Failed to resolve Hermes runtime provider for embeddings: {exc}")
        runtime = None

    if not runtime:
        return None

    resolved_provider = str(runtime.get("provider") or "").strip().lower()
    resolved_base_url = str(runtime.get("base_url") or "").strip()
    resolved_api_key = str(runtime.get("api_key") or runtime.get("api") or "").strip()
    resolved_model = str(runtime.get("model") or "").strip()

    if resolved_provider not in SUPPORTED_EMBEDDING_PROVIDERS and not resolved_base_url:
        return None

    if resolved_provider == "custom" and not resolved_base_url:
        return None

    if not resolved_model:
        return None

    embedding_provider = {
        "provider": resolved_provider or "custom",
        "model": resolved_model,
    }
    if resolved_base_url:
        embedding_provider["base_url"] = resolved_base_url
    if resolved_api_key:
        embedding_provider["api_key"] = resolved_api_key

    return embedding_provider


def _index_entry(
    *,
    namespace: str,
    thread_id: str,
    entry_id: str,
    source_type: str,
    source_id: str,
    content: str,
    metadata: dict,
    hook_kwargs: Optional[dict] = None,
) -> None:
    text = content.strip()
    if not text:
        return
    beu = get_beu()
    embedding_provider = _resolve_embedding_provider(
        namespace=namespace,
        kwargs=hook_kwargs or {},
    )
    payload = {
        "namespace": namespace,
        "embed": bool(embedding_provider),
        "embedding_provider": embedding_provider,
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


def pre_llm_call_hook(**kwargs) -> Optional[str]:
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
            source_type="user_turn",
            source_id=str(kwargs.get("session_id") or namespace),
            content=str(user_message),
            metadata={
                "kind": "user_turn",
                "session_id": kwargs.get("session_id"),
                "model": kwargs.get("model"),
                "platform": kwargs.get("platform"),
            },
            hook_kwargs=kwargs,
        )

    try:
        return None

    except Exception as e:
        logger.warning(f"pre_llm_call hook failed: {e}")
        return None


def post_llm_call_hook(**kwargs) -> Optional[dict]:
    """Hook that runs after each LLM call.

    Could trigger distillation if configured. For now, this is a
    no-op since distillation requires explicit triggering.
    """
    namespace = _resolve_namespace(kwargs)
    assistant_response = kwargs.get("assistant_response") or kwargs.get("response")
    if assistant_response:
        _index_entry(
            namespace=namespace,
            thread_id=str(kwargs.get("session_id") or namespace),
            entry_id=f"{kwargs.get('session_id', namespace)}:{kwargs.get('model', 'llm')}:assistant",
            source_type="assistant_turn",
            source_id=str(kwargs.get("session_id") or namespace),
            content=str(assistant_response),
            metadata={
                "kind": "agent_turn",
                "session_id": kwargs.get("session_id"),
                "model": kwargs.get("model"),
                "platform": kwargs.get("platform"),
            },
            hook_kwargs=kwargs,
        )
    return None


def post_tool_call_hook(tool_name: str, args: dict, result: Any, task_id: str, **kwargs) -> None:
    namespace = _resolve_namespace(kwargs)
    _index_entry(
        namespace=namespace,
        thread_id=str(kwargs.get("session_id") or task_id or namespace),
        entry_id=f"{task_id}:{tool_name}:tool",
        source_type="tool_result",
        source_id=str(kwargs.get("tool_call_id") or tool_name),
        content=result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
        metadata={
            "kind": "tool_result",
            "tool_name": tool_name,
            "task_id": task_id,
            "tool_call_id": kwargs.get("tool_call_id"),
        },
        hook_kwargs=kwargs,
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
