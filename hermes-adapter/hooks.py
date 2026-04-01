from __future__ import annotations

import json
import os
from typing import Any, Optional

from ._shared import DEFAULT_DISTILL_HOOK_THRESHOLD, DEFAULT_NAMESPACE, logger
from .config import (
    _candidate_distill_payloads,
    _collect_beu_embedding_settings,
    _resolve_embedding_provider,
)


_ROOT = None

def _resolve_namespace(kwargs: dict) -> str:
    return kwargs.get("session_key") or kwargs.get("session_id") or kwargs.get("task_id") or DEFAULT_NAMESPACE


def _distill_threshold() -> int:
    try:
        value = int(os.environ.get("BEU_DISTILL_HOOK_THRESHOLD", "").strip() or 0)
        return value if value > 0 else DEFAULT_DISTILL_HOOK_THRESHOLD
    except Exception:
        return DEFAULT_DISTILL_HOOK_THRESHOLD


def _note_hook(namespace: str) -> bool:
    return True


def _reset_hook_count(namespace: str) -> None:
    return None


def _trigger_backend_distill(namespace: str, thread_id: str, turn_id: str, *, force: bool = False) -> None:
    logger.info(
        "BeU distill trigger: namespace=%s thread_id=%s turn_id=%s force=%s",
        namespace,
        thread_id,
        turn_id,
        force,
    )
    tick = _ROOT.get_beu().distill_tick(
        {"thread_id": thread_id, "turn_id": turn_id, "event_kind": "session_end" if force else "hook"},
        namespace=namespace,
    )
    hook_count = int(tick.get("hook_count", 0) or 0)
    threshold = _distill_threshold()
    logger.info(
        "BeU distill tick: namespace=%s thread_id=%s turn_id=%s hook_count=%s threshold=%s force=%s",
        namespace,
        thread_id,
        turn_id,
        hook_count,
        threshold,
        force,
    )
    if not force and hook_count < threshold:
        logger.info(
            "BeU distill skipped: namespace=%s thread_id=%s hook_count=%s threshold=%s",
            namespace,
            thread_id,
            hook_count,
            threshold,
        )
        return
    payload = next((candidate for candidate in _candidate_distill_payloads() if candidate), {})
    payload = {"thread_id": thread_id, "turn_id": turn_id, "limit": int(os.environ.get("BEU_DISTILL_HISTORY_LIMIT", "").strip() or 48), **payload}
    logger.info(
        "BeU distill firing: namespace=%s thread_id=%s turn_id=%s provider=%s model=%s limit=%s",
        namespace,
        thread_id,
        turn_id,
        payload.get("provider"),
        payload.get("model"),
        payload.get("limit"),
    )
    try:
        result = _ROOT.get_beu().distill(payload, namespace=namespace)
        if not result:
            logger.warning("Backend distill failed")
            return
        logger.info(
            "BeU distill completed: namespace=%s thread_id=%s turn_id=%s facts=%s invariants=%s",
            namespace,
            thread_id,
            turn_id,
            len(result.get("facts", []) or []),
            len(result.get("invariant_adds", []) or []),
        )
        _ROOT.get_beu().distill_reset(
            {"thread_id": thread_id, "turn_id": turn_id, "event_kind": "distilled"},
            namespace=namespace,
        )
        logger.info(
            "BeU distill reset: namespace=%s thread_id=%s turn_id=%s",
            namespace,
            thread_id,
            turn_id,
        )
    finally:
        _reset_hook_count(namespace)


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
    beu = _ROOT.get_beu()
    embedding_provider = _ROOT._resolve_embedding_provider(
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
                "source_id": str(
                    metadata.get("tool_call_id") or metadata.get("run_id") or source_id or entry_id
                ),
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
    namespace = _resolve_namespace(kwargs)
    thread_id = str(kwargs.get("session_id") or namespace)
    turn_id = str(kwargs.get("turn_id") or kwargs.get("task_id") or thread_id)
    user_message = kwargs.get("user_message", "")
    if user_message:
        _index_entry(
            namespace=namespace,
            thread_id=thread_id,
            entry_id=f"{kwargs.get('session_id', namespace)}:{kwargs.get('model', 'llm')}:user",
            source_type="user_turn",
            source_id=str(kwargs.get("session_id") or namespace),
            content=str(user_message),
            metadata={"kind": "user_turn", "session_id": kwargs.get("session_id"), "model": kwargs.get("model"), "platform": kwargs.get("platform")},
            hook_kwargs=kwargs,
        )
    try:
        query = str(user_message or kwargs.get("system_prompt") or "").strip()
        if not query:
            return None
        _trigger_backend_distill(namespace, thread_id, turn_id)
        result = _ROOT.get_beu().recall(query=query, namespace=namespace, limit=6)
        block = result.get("ledger_recall_block")
        return block if isinstance(block, str) and block.strip() else None
    except Exception as e:
        logger.warning("pre_llm_call hook failed: %s", e)
        return None


def post_llm_call_hook(**kwargs) -> Optional[dict]:
    namespace = _resolve_namespace(kwargs)
    thread_id = str(kwargs.get("session_id") or namespace)
    turn_id = str(kwargs.get("turn_id") or kwargs.get("task_id") or thread_id)
    assistant_response = kwargs.get("assistant_response") or kwargs.get("response")
    if assistant_response:
        _index_entry(
            namespace=namespace,
            thread_id=thread_id,
            entry_id=f"{kwargs.get('session_id', namespace)}:{kwargs.get('model', 'llm')}:assistant",
            source_type="assistant_turn",
            source_id=str(kwargs.get("session_id") or namespace),
            content=str(assistant_response),
            metadata={"kind": "agent_turn", "session_id": kwargs.get("session_id"), "model": kwargs.get("model"), "platform": kwargs.get("platform")},
            hook_kwargs=kwargs,
        )
    _trigger_backend_distill(namespace, thread_id, turn_id)
    return None


def post_tool_call_hook(tool_name: str, args: dict, result: Any, task_id: str, **kwargs) -> None:
    namespace = _resolve_namespace(kwargs)
    thread_id = str(kwargs.get("session_id") or task_id or namespace)
    turn_id = str(kwargs.get("turn_id") or task_id or thread_id)
    _index_entry(
        namespace=namespace,
        thread_id=thread_id,
        entry_id=f"{task_id}:{tool_name}:tool",
        source_type="tool_result",
        source_id=str(kwargs.get("tool_call_id") or tool_name),
        content=result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
        metadata={"kind": "tool_result", "tool_name": tool_name, "task_id": task_id, "tool_call_id": kwargs.get("tool_call_id")},
        hook_kwargs=kwargs,
    )
    _trigger_backend_distill(namespace, thread_id, turn_id)


def on_session_start_hook(**kwargs) -> None:
    logger.info("BeU memory initialized")


def on_session_end_hook(**kwargs) -> None:
    namespace = _resolve_namespace(kwargs)
    thread_id = str(kwargs.get("session_id") or namespace)
    turn_id = str(kwargs.get("turn_id") or thread_id)
    _trigger_backend_distill(namespace, thread_id, turn_id, force=True)
