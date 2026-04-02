from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ._shared import DEFAULT_NAMESPACE, logger
from .config import DurableLedgerSettings


CHUNK_SIZE = 1200
TABLE_FILES = (
    "workspaces.jsonl",
    "agents.jsonl",
    "threads.jsonl",
    "turns.jsonl",
    "events.jsonl",
    "distill_state.jsonl",
    "ledger_entries.jsonl",
    "ledger_entry_chunks.jsonl",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha1("::".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:16]}"


def _sanitize_namespace(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    candidate = candidate.strip(".-_")
    if candidate:
        return candidate[:80]
    return f"ns-{hashlib.sha1(value.encode('utf-8')).hexdigest()[:16]}"


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _chunk_text(value: str, size: int = CHUNK_SIZE) -> list[str]:
    text = value.strip()
    if not text:
        return []
    return [text[index : index + size] for index in range(0, len(text), size)]


def _safe_json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                loaded = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping unreadable JSONL line in %s", path)
                continue
            if isinstance(loaded, dict):
                records.append(loaded)
    return records


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_safe_json_dumps(record))
        handle.write("\n")


def _latest_record(path: Path, key: str, value: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for record in _iter_jsonl(path):
        if str(record.get(key) or "") == value:
            latest = record
    return latest


def _latest_record_where(path: Path, predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for record in _iter_jsonl(path):
        if predicate(record):
            latest = record
    return latest


class JsonlLedgerStore:
    def __init__(self, settings: DurableLedgerSettings):
        self.settings = settings

    def on_session_start(self, kwargs: dict[str, Any]) -> None:
        context = self._context(kwargs)
        self._ensure_namespace_files(context["namespace_dir"])
        self._upsert_workspace(context)
        self._upsert_agent(context)
        self._upsert_thread(context, title=self._thread_title(kwargs))
        self._append_distill_state(context, None, "session_start")

    def pre_llm_call(self, kwargs: dict[str, Any]) -> None:
        context = self._context(kwargs)
        self._ensure_namespace_files(context["namespace_dir"])
        self._upsert_workspace(context)
        self._upsert_agent(context)
        self._upsert_thread(context, title=self._thread_title(kwargs))
        turn_id = self._resolve_turn_id(context, kwargs, create_if_missing=True)
        user_message = str(
            kwargs.get("user_message")
            or kwargs.get("prompt")
            or kwargs.get("message")
            or ""
        )
        self._upsert_turn(
            context,
            turn_id,
            {
                "status": "open",
                "user_message": user_message,
                "assistant_message": None,
                "error": None,
            },
        )
        self._append_event(
            context,
            turn_id,
            "user_turn",
            {
                "message": user_message,
                "metadata": self._metadata(kwargs),
            },
        )
        self._append_ledger_entry(
            context,
            entry_id=f"{turn_id}:user",
            entry_type="user_turn",
            source_type="user_turn",
            source_id=turn_id,
            turn_id=turn_id,
            title="User turn",
            summary=self._summary(user_message),
            citation=turn_id,
            payload={
                "content": user_message,
                "metadata": self._metadata(kwargs) | {"thread_id": context["thread_id"]},
            },
        )
        self._append_distill_state(context, turn_id, "user_turn")

    def post_llm_call(self, kwargs: dict[str, Any]) -> None:
        context = self._context(kwargs)
        self._ensure_namespace_files(context["namespace_dir"])
        self._upsert_workspace(context)
        self._upsert_agent(context)
        self._upsert_thread(context, title=self._thread_title(kwargs))
        turn_id = self._resolve_turn_id(context, kwargs, create_if_missing=True)
        assistant_message = str(
            kwargs.get("assistant_response")
            or kwargs.get("assistant_message")
            or kwargs.get("response")
            or ""
        )
        error = kwargs.get("error")
        status = "error" if error else "completed"
        self._upsert_turn(
            context,
            turn_id,
            {
                "status": status,
                "assistant_message": assistant_message or None,
                "error": None if error in (None, "") else str(error),
            },
        )
        if assistant_message:
            self._append_event(
                context,
                turn_id,
                "assistant_turn",
                {
                    "message": assistant_message,
                    "metadata": self._metadata(kwargs),
                },
            )
            self._append_ledger_entry(
                context,
                entry_id=f"{turn_id}:assistant",
                entry_type="assistant_turn",
                source_type="assistant_turn",
                source_id=turn_id,
                turn_id=turn_id,
                title="Assistant turn",
                summary=self._summary(assistant_message),
                citation=turn_id,
                payload={
                    "content": assistant_message,
                    "metadata": self._metadata(kwargs) | {"thread_id": context["thread_id"]},
                },
            )
        if error not in (None, ""):
            self._append_event(
                context,
                turn_id,
                "error",
                {
                    "error": str(error),
                    "metadata": self._metadata(kwargs),
                },
            )
            self._append_ledger_entry(
                context,
                entry_id=f"{turn_id}:error",
                entry_type="error",
                source_type="error",
                source_id=turn_id,
                turn_id=turn_id,
                title="Turn error",
                summary=self._summary(str(error)),
                citation=turn_id,
                payload={
                    "error": str(error),
                    "metadata": self._metadata(kwargs) | {"thread_id": context["thread_id"]},
                },
            )
        self._append_distill_state(context, turn_id, "error" if error else "assistant_turn")

    def post_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any] | None,
        result: Any,
        task_id: str | None,
        **kwargs: Any,
    ) -> None:
        payload_kwargs = dict(kwargs)
        if task_id:
            payload_kwargs.setdefault("task_id", task_id)
        context = self._context(payload_kwargs)
        self._ensure_namespace_files(context["namespace_dir"])
        self._upsert_workspace(context)
        self._upsert_agent(context)
        self._upsert_thread(context, title=self._thread_title(payload_kwargs))
        turn_id = self._resolve_turn_id(context, payload_kwargs, create_if_missing=True)
        tool_call_id = str(payload_kwargs.get("tool_call_id") or payload_kwargs.get("call_id") or uuid.uuid4())
        serialized_result = result if isinstance(result, str) else _safe_json_dumps(result)
        payload = {
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "args": args or {},
            "result": serialized_result,
            "metadata": self._metadata(payload_kwargs) | {"thread_id": context["thread_id"]},
        }
        self._append_event(context, turn_id, "tool_result", payload)
        self._append_ledger_entry(
            context,
            entry_id=f"{turn_id}:tool:{tool_call_id}",
            entry_type="tool_result",
            source_type="tool_result",
            source_id=tool_call_id,
            turn_id=turn_id,
            title=f"Tool result: {tool_name}",
            summary=self._summary(serialized_result),
            citation=tool_call_id,
            payload=payload,
        )
        self._append_distill_state(context, turn_id, "tool_result")

    def on_session_end(self, kwargs: dict[str, Any]) -> None:
        context = self._context(kwargs)
        self._ensure_namespace_files(context["namespace_dir"])
        self._upsert_workspace(context)
        self._upsert_agent(context)
        self._upsert_thread(context, title=self._thread_title(kwargs))
        turn_id = self._resolve_turn_id(context, kwargs, create_if_missing=False)
        self._append_distill_state(context, turn_id, "session_end")

    def _context(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        namespace = self._resolve_namespace(kwargs)
        namespace_dir = self.settings.storage_root / "v1" / "namespaces" / _sanitize_namespace(namespace)
        workspace_root = str(
            kwargs.get("workspace_root")
            or kwargs.get("cwd")
            or kwargs.get("workspace")
            or Path.cwd()
        )
        agent_hint = str(kwargs.get("agent_id") or kwargs.get("platform") or "hermes")
        external_thread_id = str(
            kwargs.get("session_key")
            or kwargs.get("session_id")
            or kwargs.get("task_id")
            or DEFAULT_NAMESPACE
        )
        channel = str(kwargs.get("platform") or "hermes")
        workspace_id = _stable_id("workspace", workspace_root)
        agent_id = _stable_id("agent", workspace_id, agent_hint)
        thread_id = _stable_id("thread", agent_id, channel, external_thread_id)
        return {
            "namespace": namespace,
            "namespace_dir": namespace_dir,
            "workspace_root": workspace_root,
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "thread_id": thread_id,
            "external_thread_id": external_thread_id,
            "channel": channel,
        }

    def _resolve_namespace(self, kwargs: dict[str, Any]) -> str:
        for key in self.settings.namespace_strategy:
            if key == "default":
                return DEFAULT_NAMESPACE
            value = kwargs.get(key)
            if value not in (None, ""):
                return str(value)
        return DEFAULT_NAMESPACE

    def _ensure_namespace_files(self, namespace_dir: Path) -> None:
        namespace_dir.mkdir(parents=True, exist_ok=True)
        for file_name in TABLE_FILES:
            path = namespace_dir / file_name
            if not path.exists():
                path.touch()

    def _upsert_workspace(self, context: dict[str, Any]) -> None:
        path = context["namespace_dir"] / "workspaces.jsonl"
        existing = _latest_record(path, "id", context["workspace_id"])
        now = _now()
        _append_jsonl(
            path,
            {
                "id": context["workspace_id"],
                "root": context["workspace_root"],
                "created_at": existing.get("created_at") if existing else now,
            },
        )

    def _upsert_agent(self, context: dict[str, Any]) -> None:
        path = context["namespace_dir"] / "agents.jsonl"
        existing = _latest_record(path, "id", context["agent_id"])
        now = _now()
        _append_jsonl(
            path,
            {
                "id": context["agent_id"],
                "display_name": "Hermes Durable Ledger",
                "workspace_id": context["workspace_id"],
                "created_at": existing.get("created_at") if existing else now,
            },
        )

    def _upsert_thread(self, context: dict[str, Any], title: str) -> None:
        path = context["namespace_dir"] / "threads.jsonl"
        existing = _latest_record(path, "id", context["thread_id"])
        now = _now()
        record = {
            "id": context["thread_id"],
            "agent_id": context["agent_id"],
            "channel": context["channel"],
            "external_thread_id": context["external_thread_id"],
            "title": title,
            "metadata_json": _safe_json_dumps(
                {
                    "namespace": context["namespace"],
                    "workspace_root": context["workspace_root"],
                }
            ),
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
        }
        _append_jsonl(path, record)

    def _resolve_turn_id(self, context: dict[str, Any], kwargs: dict[str, Any], create_if_missing: bool) -> str | None:
        explicit = kwargs.get("turn_id")
        if explicit not in (None, ""):
            return str(explicit)
        latest_state = _latest_record_where(
            context["namespace_dir"] / "distill_state.jsonl",
            lambda record: record.get("namespace_id") == context["namespace"]
            and record.get("thread_id") == context["thread_id"],
        )
        if latest_state and latest_state.get("last_turn_id"):
            return str(latest_state["last_turn_id"])
        if create_if_missing:
            return _stable_id("turn", context["thread_id"], uuid.uuid4())
        return None

    def _upsert_turn(self, context: dict[str, Any], turn_id: str, update: dict[str, Any]) -> None:
        path = context["namespace_dir"] / "turns.jsonl"
        existing = _latest_record(path, "id", turn_id) or {}
        now = _now()
        record = {
            "id": turn_id,
            "thread_id": context["thread_id"],
            "status": update.get("status") or existing.get("status") or "open",
            "user_message": update.get("user_message")
            if update.get("user_message") is not None
            else existing.get("user_message")
            or "",
            "assistant_message": update.get("assistant_message")
            if "assistant_message" in update
            else existing.get("assistant_message"),
            "error": update.get("error") if "error" in update else existing.get("error"),
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
        _append_jsonl(path, record)

    def _append_event(self, context: dict[str, Any], turn_id: str, kind: str, payload: dict[str, Any]) -> None:
        path = context["namespace_dir"] / "events.jsonl"
        sequence = 1
        for record in _iter_jsonl(path):
            if record.get("turn_id") == turn_id:
                sequence = max(sequence, int(record.get("sequence") or 0) + 1)
        _append_jsonl(
            path,
            {
                "id": _stable_id("event", turn_id, sequence, uuid.uuid4()),
                "turn_id": turn_id,
                "thread_id": context["thread_id"],
                "sequence": sequence,
                "kind": kind,
                "payload": _safe_json_dumps(payload),
                "created_at": _now(),
            },
        )

    def _append_distill_state(self, context: dict[str, Any], turn_id: str | None, event_kind: str) -> None:
        path = context["namespace_dir"] / "distill_state.jsonl"
        latest = _latest_record_where(
            path,
            lambda record: record.get("namespace_id") == context["namespace"]
            and record.get("thread_id") == context["thread_id"],
        )
        hook_count = int(latest.get("hook_count") or 0) + 1 if latest else 1
        _append_jsonl(
            path,
            {
                "namespace_id": context["namespace"],
                "thread_id": context["thread_id"],
                "hook_count": hook_count,
                "last_turn_id": turn_id,
                "last_event_kind": event_kind,
                "last_distilled_at": latest.get("last_distilled_at") if latest else None,
                "updated_at": _now(),
            },
        )

    def _append_ledger_entry(
        self,
        context: dict[str, Any],
        entry_id: str,
        entry_type: str,
        source_type: str,
        source_id: str,
        turn_id: str | None,
        title: str,
        summary: str | None,
        citation: str,
        payload: dict[str, Any],
    ) -> None:
        path = context["namespace_dir"] / "ledger_entries.jsonl"
        existing = _latest_record(path, "id", entry_id) or {}
        now = _now()
        payload_json = _safe_json_dumps(payload)
        record = {
            "id": entry_id,
            "namespace_id": context["namespace"],
            "entry_type": entry_type,
            "source_type": source_type,
            "source_id": source_id,
            "thread_id": context["thread_id"],
            "turn_id": turn_id,
            "title": title,
            "summary": summary,
            "citation": citation,
            "payload_json": payload_json,
            "importance": 0,
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
            "deleted_at": None,
        }
        _append_jsonl(path, record)
        content = "\n\n".join(part for part in (title, summary or "", payload_json) if part)
        chunk_path = context["namespace_dir"] / "ledger_entry_chunks.jsonl"
        hints_json = _safe_json_dumps(
            {
                "entry_type": entry_type,
                "source_type": source_type,
                "source_id": source_id,
            }
        )
        for index, chunk in enumerate(_chunk_text(content)):
            _append_jsonl(
                chunk_path,
                {
                    "chunk_id": _stable_id("chunk", entry_id, index, now),
                    "namespace_id": context["namespace"],
                    "entry_id": entry_id,
                    "chunk_index": index,
                    "content": chunk,
                    "content_norm": _normalize_text(chunk),
                    "search_hints_json": hints_json,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    def _thread_title(self, kwargs: dict[str, Any]) -> str:
        candidate = str(
            kwargs.get("title")
            or kwargs.get("user_message")
            or kwargs.get("prompt")
            or kwargs.get("task_id")
            or "Hermes session"
        ).strip()
        return candidate[:120] or "Hermes session"

    def _metadata(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        allowed = (
            "session_id",
            "session_key",
            "task_id",
            "turn_id",
            "model",
            "platform",
            "provider",
            "cwd",
            "workspace_root",
            "tool_call_id",
            "duration_ms",
        )
        return {key: kwargs.get(key) for key in allowed if kwargs.get(key) not in (None, "")}

    def _summary(self, value: str) -> str | None:
        text = value.strip()
        if not text:
            return None
        return text[:240]