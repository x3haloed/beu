from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


CHUNK_SIZE = 1200
RUNTIME_STATE_MAX_AGE_SECONDS = 900
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

WORKSPACE_MARKERS = (
    ".git",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
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


@dataclass(frozen=True)
class Settings:
    storage_root: Path
    namespace: str


def _load_settings_file(config_dir: Path) -> dict[str, Any]:
    config_path = config_dir / "durable-ledger.json"
    if not config_path.is_file():
        return {}
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _resolve_workspace_root(start_path: Path) -> Path:
    for candidate in (start_path, *start_path.parents):
        if any((candidate / marker).exists() for marker in WORKSPACE_MARKERS):
            return candidate
    return start_path


def _default_namespace(workspace_root: Path) -> str:
    label = workspace_root.name.strip() or "workspace"
    digest = hashlib.sha1(str(workspace_root).encode("utf-8")).hexdigest()[:8]
    return _sanitize_namespace(f"{label}-{digest}")


def _parse_rfc3339(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_settings(cwd: str | None) -> Settings:
    workspace_root = _resolve_workspace_root(Path(cwd or os.getcwd()).expanduser().resolve())
    config_dir = Path.home() / ".copilot"
    config = _load_settings_file(config_dir)
    storage_root_value = os.environ.get("DURABLE_LEDGER_STORAGE_ROOT", "").strip() or str(
        config.get("storageRoot") or ""
    ).strip()
    if storage_root_value:
        storage_root = Path(storage_root_value).expanduser()
        if not storage_root.is_absolute():
            storage_root = (config_dir / storage_root).resolve()
    else:
        storage_root = config_dir / "state" / "durable-ledger"
    namespace_override = os.environ.get("DURABLE_LEDGER_NAMESPACE", "").strip()
    namespace_config = str(config.get("namespace") or "").strip()
    namespace = namespace_override or namespace_config or _default_namespace(workspace_root)
    return Settings(storage_root=storage_root, namespace=_sanitize_namespace(namespace))


class CopilotCliLedgerStore:
    def __init__(self, settings: Settings):
        self.settings = settings

    def handle_session_start(self, payload: dict[str, Any]) -> None:
        context = self._context(payload)
        self._ensure_namespace_files(context["namespace_dir"])
        self._upsert_workspace(context)
        self._upsert_agent(context)
        thread_id = self._session_thread_id(payload, context)
        existing_state = self._load_runtime_state(context, payload)
        context["thread_id"] = thread_id
        self._upsert_thread(context, self._thread_title(payload))
        self._write_runtime_state(
            context,
            {
                "session_id": thread_id,
                "thread_id": thread_id,
                "current_turn_id": existing_state.get("current_turn_id"),
                "source": payload.get("source") or "new",
                "started_at": existing_state.get("started_at") or self._timestamp_to_rfc3339(payload.get("timestamp")),
            },
        )
        self._append_distill_state(context, None, "session_start")
        self._append_ledger_entry(
            context,
            entry_id=f"{thread_id}:session_start",
            entry_type="trace_summary",
            source_type="session_start",
            source_id=thread_id,
            turn_id=None,
            title="Session start",
            summary=self._summary(str(payload.get("initialPrompt") or payload.get("source") or "session start")),
            citation=thread_id,
            payload={
                "event": "session_start",
                "source": payload.get("source"),
                "initial_prompt": payload.get("initialPrompt"),
                "metadata": {"thread_id": thread_id, "cwd": context["active_cwd"]},
            },
        )

    def handle_user_prompt_submitted(self, payload: dict[str, Any]) -> None:
        context = self._context(payload)
        self._ensure_namespace_files(context["namespace_dir"])
        self._upsert_workspace(context)
        self._upsert_agent(context)
        thread_id = self._ensure_active_thread(context, payload)
        context["thread_id"] = thread_id
        self._upsert_thread(context, self._thread_title(payload))
        turn_id = _stable_id("turn", thread_id, payload.get("timestamp") or uuid.uuid4())
        prompt = str(payload.get("prompt") or "")
        self._upsert_turn(
            context,
            turn_id,
            {
                "status": "open",
                "user_message": prompt,
                "assistant_message": None,
                "error": None,
            },
        )
        self._append_event(
            context,
            turn_id,
            "user_turn",
            {
                "message": prompt,
                "metadata": {"thread_id": thread_id, "cwd": context["active_cwd"]},
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
            summary=self._summary(prompt),
            citation=turn_id,
            payload={
                "content": prompt,
                "metadata": {"thread_id": thread_id, "cwd": context["active_cwd"]},
            },
        )
        self._append_distill_state(context, turn_id, "user_turn")
        self._update_runtime_state(context, current_turn_id=turn_id)

    def handle_pre_tool_use(self, payload: dict[str, Any]) -> None:
        context = self._context(payload)
        self._ensure_namespace_files(context["namespace_dir"])
        thread_id = self._ensure_active_thread(context, payload)
        context["thread_id"] = thread_id
        turn_id = self._ensure_active_turn(context, thread_id)
        tool_name = str(payload.get("toolName") or "unknown")
        tool_args = self._parse_tool_args(payload.get("toolArgs"))
        tool_call_id = _stable_id("tool", turn_id, tool_name, payload.get("timestamp") or uuid.uuid4())
        event_payload = {
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "tool_args": tool_args,
            "metadata": {"thread_id": thread_id, "cwd": context["active_cwd"]},
        }
        self._append_event(context, turn_id, "tool_call", event_payload)
        self._append_ledger_entry(
            context,
            entry_id=f"{turn_id}:tool_call:{tool_call_id}",
            entry_type="tool_call",
            source_type="tool_call",
            source_id=tool_call_id,
            turn_id=turn_id,
            title=f"Tool call: {tool_name}",
            summary=self._summary(_safe_json_dumps(tool_args)),
            citation=tool_call_id,
            payload=event_payload,
        )
        self._append_distill_state(context, turn_id, "tool_call")
        self._update_runtime_state(context, current_turn_id=turn_id)

    def handle_post_tool_use(self, payload: dict[str, Any]) -> None:
        context = self._context(payload)
        self._ensure_namespace_files(context["namespace_dir"])
        thread_id = self._ensure_active_thread(context, payload)
        context["thread_id"] = thread_id
        turn_id = self._ensure_active_turn(context, thread_id)
        tool_name = str(payload.get("toolName") or "unknown")
        tool_args = self._parse_tool_args(payload.get("toolArgs"))
        tool_result = payload.get("toolResult") if isinstance(payload.get("toolResult"), dict) else {}
        tool_call_id = _stable_id("tool", turn_id, tool_name, payload.get("timestamp") or uuid.uuid4())
        serialized_result = _safe_json_dumps(tool_result)
        event_payload = {
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "tool_args": tool_args,
            "tool_result": tool_result,
            "metadata": {"thread_id": thread_id, "cwd": context["active_cwd"]},
        }
        self._append_event(context, turn_id, "tool_result", event_payload)
        self._append_ledger_entry(
            context,
            entry_id=f"{turn_id}:tool_result:{tool_call_id}",
            entry_type="tool_result",
            source_type="tool_result",
            source_id=tool_call_id,
            turn_id=turn_id,
            title=f"Tool result: {tool_name}",
            summary=self._summary(serialized_result),
            citation=tool_call_id,
            payload=event_payload,
        )
        if str(tool_result.get("resultType") or "") == "failure":
            self._upsert_turn(
                context,
                turn_id,
                {
                    "status": "error",
                    "error": str(tool_result.get("textResultForLlm") or "tool failure"),
                },
            )
        self._append_distill_state(context, turn_id, "tool_result")

    def handle_error_occurred(self, payload: dict[str, Any]) -> None:
        context = self._context(payload)
        self._ensure_namespace_files(context["namespace_dir"])
        thread_id = self._ensure_active_thread(context, payload)
        context["thread_id"] = thread_id
        turn_id = self._ensure_active_turn(context, thread_id)
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        message = str(error.get("message") or "unknown error")
        event_payload = {
            "error": error,
            "metadata": {"thread_id": thread_id, "cwd": context["active_cwd"]},
        }
        self._upsert_turn(context, turn_id, {"status": "error", "error": message})
        self._append_event(context, turn_id, "error", event_payload)
        self._append_ledger_entry(
            context,
            entry_id=f"{turn_id}:error",
            entry_type="error",
            source_type="error",
            source_id=turn_id,
            turn_id=turn_id,
            title="Execution error",
            summary=self._summary(message),
            citation=turn_id,
            payload=event_payload,
        )
        self._append_distill_state(context, turn_id, "error")

    def handle_session_end(self, payload: dict[str, Any]) -> None:
        context = self._context(payload)
        self._ensure_namespace_files(context["namespace_dir"])
        thread_id = self._ensure_active_thread(context, payload)
        context["thread_id"] = thread_id
        turn_id = self._load_runtime_state(context).get("current_turn_id")
        reason = str(payload.get("reason") or "complete")
        self._append_distill_state(context, turn_id, "session_end")
        self._append_ledger_entry(
            context,
            entry_id=f"{thread_id}:session_end",
            entry_type="trace_summary",
            source_type="session_end",
            source_id=thread_id,
            turn_id=turn_id,
            title="Session end",
            summary=self._summary(reason),
            citation=thread_id,
            payload={
                "event": "session_end",
                "reason": reason,
                "metadata": {"thread_id": thread_id, "cwd": context["active_cwd"]},
            },
        )
        self._clear_runtime_state(context)

    def _context(self, payload: dict[str, Any]) -> dict[str, Any]:
        workspace_path = _resolve_workspace_root(Path(str(payload.get("cwd") or os.getcwd())).expanduser().resolve())
        workspace_root = str(workspace_path)
        workspace_id = _stable_id("workspace", workspace_path)
        agent_id = _stable_id("agent", workspace_id, "copilot-cli")
        namespace_dir = self.settings.storage_root / "v1" / "namespaces" / self.settings.namespace
        return {
            "namespace": self.settings.namespace,
            "namespace_dir": namespace_dir,
            "workspace_root": workspace_root,
            "active_cwd": str(payload.get("cwd") or os.getcwd()),
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "channel": "copilot-cli",
        }

    def _ensure_namespace_files(self, namespace_dir: Path) -> None:
        namespace_dir.mkdir(parents=True, exist_ok=True)
        for file_name in TABLE_FILES:
            path = namespace_dir / file_name
            if not path.exists():
                path.touch()

    def _runtime_state_path(self, context: dict[str, Any]) -> Path:
        return context["namespace_dir"] / ".runtime-state.json"

    def _load_runtime_state(self, context: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        path = self._runtime_state_path(context)
        if not path.is_file():
            return {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(loaded, dict):
            return {}
        if not self._runtime_state_is_fresh(loaded, payload):
            self._clear_runtime_state(context)
            return {}
        return loaded

    def _write_runtime_state(self, context: dict[str, Any], state: dict[str, Any]) -> None:
        path = self._runtime_state_path(context)
        path.parent.mkdir(parents=True, exist_ok=True)
        state_to_write = dict(state)
        state_to_write["updated_at"] = _now()
        path.write_text(_safe_json_dumps(state_to_write), encoding="utf-8")

    def _update_runtime_state(self, context: dict[str, Any], **updates: Any) -> None:
        state = self._load_runtime_state(context)
        state.update(updates)
        self._write_runtime_state(context, state)

    def _runtime_state_is_fresh(self, state: dict[str, Any], payload: dict[str, Any] | None) -> bool:
        reference_time = _parse_rfc3339(state.get("updated_at")) or _parse_rfc3339(state.get("started_at"))
        if reference_time is None:
            return False
        payload_timestamp = payload.get("timestamp") if isinstance(payload, dict) else None
        if isinstance(payload_timestamp, (int, float)):
            event_time = datetime.fromtimestamp(payload_timestamp / 1000, tz=timezone.utc)
        else:
            event_time = datetime.now(timezone.utc)
        return abs((event_time - reference_time).total_seconds()) <= RUNTIME_STATE_MAX_AGE_SECONDS

    def _clear_runtime_state(self, context: dict[str, Any]) -> None:
        path = self._runtime_state_path(context)
        if path.exists():
            path.unlink()

    def _session_thread_id(self, payload: dict[str, Any], context: dict[str, Any]) -> str:
        state = self._load_runtime_state(context, payload)
        if state.get("thread_id"):
            return str(state["thread_id"])
        source = str(payload.get("source") or "new")
        timestamp = payload.get("timestamp") or uuid.uuid4()
        return _stable_id("thread", context["agent_id"], context["channel"], timestamp, source)

    def _ensure_active_thread(self, context: dict[str, Any], payload: dict[str, Any]) -> str:
        state = self._load_runtime_state(context, payload)
        if state.get("thread_id"):
            return str(state["thread_id"])
        thread_id = self._session_thread_id(payload, context)
        self._write_runtime_state(
            context,
            {
                "session_id": thread_id,
                "thread_id": thread_id,
                "current_turn_id": state.get("current_turn_id"),
                "source": payload.get("source") or "startup",
                "started_at": state.get("started_at") or self._timestamp_to_rfc3339(payload.get("timestamp")),
            },
        )
        self._upsert_workspace(context)
        self._upsert_agent(context)
        context["thread_id"] = thread_id
        self._upsert_thread(context, self._thread_title(payload))
        return thread_id

    def _ensure_active_turn(self, context: dict[str, Any], thread_id: str) -> str:
        state = self._load_runtime_state(context)
        if state.get("current_turn_id"):
            return str(state["current_turn_id"])
        turn_id = _stable_id("turn", thread_id, uuid.uuid4())
        self._upsert_turn(
            context,
            turn_id,
            {
                "status": "open",
                "user_message": "",
                "assistant_message": None,
                "error": None,
            },
        )
        self._update_runtime_state(context, current_turn_id=turn_id)
        return turn_id

    def _upsert_workspace(self, context: dict[str, Any]) -> None:
        path = context["namespace_dir"] / "workspaces.jsonl"
        existing = _latest_record(path, "id", context["workspace_id"])
        _append_jsonl(
            path,
            {
                "id": context["workspace_id"],
                "root": context["workspace_root"],
                "created_at": existing.get("created_at") if existing else _now(),
            },
        )

    def _upsert_agent(self, context: dict[str, Any]) -> None:
        path = context["namespace_dir"] / "agents.jsonl"
        existing = _latest_record(path, "id", context["agent_id"])
        _append_jsonl(
            path,
            {
                "id": context["agent_id"],
                "display_name": "GitHub Copilot CLI Durable Ledger",
                "workspace_id": context["workspace_id"],
                "created_at": existing.get("created_at") if existing else _now(),
            },
        )

    def _upsert_thread(self, context: dict[str, Any], title: str) -> None:
        path = context["namespace_dir"] / "threads.jsonl"
        thread_id = context["thread_id"]
        existing = _latest_record(path, "id", thread_id)
        now = _now()
        _append_jsonl(
            path,
            {
                "id": thread_id,
                "agent_id": context["agent_id"],
                "channel": context["channel"],
                "external_thread_id": thread_id,
                "title": title,
                "metadata_json": _safe_json_dumps(
                    {
                        "namespace": context["namespace"],
                        "workspace_root": context["workspace_root"],
                    }
                ),
                "created_at": existing.get("created_at") if existing else now,
                "updated_at": now,
            },
        )

    def _upsert_turn(self, context: dict[str, Any], turn_id: str, update: dict[str, Any]) -> None:
        path = context["namespace_dir"] / "turns.jsonl"
        existing = _latest_record(path, "id", turn_id) or {}
        now = _now()
        _append_jsonl(
            path,
            {
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
            },
        )

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
        _append_jsonl(
            path,
            {
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
            },
        )
        content = "\n\n".join(part for part in (title, summary or "", payload_json) if part)
        hints_json = _safe_json_dumps(
            {
                "entry_type": entry_type,
                "source_type": source_type,
                "source_id": source_id,
            }
        )
        for index, chunk in enumerate(_chunk_text(content)):
            _append_jsonl(
                context["namespace_dir"] / "ledger_entry_chunks.jsonl",
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

    def _parse_tool_args(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return {"raw": raw}
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        return {}

    def _thread_title(self, payload: dict[str, Any]) -> str:
        candidate = str(
            payload.get("initialPrompt")
            or payload.get("prompt")
            or payload.get("toolName")
            or "Copilot CLI session"
        ).strip()
        return candidate[:120] or "Copilot CLI session"

    def _summary(self, value: str) -> str | None:
        text = value.strip()
        if not text:
            return None
        return text[:240]

    def _timestamp_to_rfc3339(self, value: Any) -> str:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
        return _now()