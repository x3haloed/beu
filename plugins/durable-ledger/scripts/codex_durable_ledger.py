#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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

WORKSPACE_MARKERS = (".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod")
DEFAULT_STORAGE_ROOT = Path.home() / ".codex" / "state" / "durable-ledger"
DEFAULT_NAMESPACE_OVERRIDE = ""
DEFAULT_WINDOW = 6
DEFAULT_WAKE_PACK = "# Wake Pack\n\n- No durable context yet."


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


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_payload() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _workspace_root(cwd: str) -> Path:
    path = Path(cwd).expanduser().resolve()
    for candidate in (path, *path.parents):
        if any((candidate / marker).exists() for marker in WORKSPACE_MARKERS):
            return candidate
    return path


def _load_settings() -> dict[str, Any]:
    config_dir = Path.home() / ".codex"
    config_path = config_dir / "durable-ledger.json"
    if not config_path.is_file():
        return {}
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _settings_for(payload: dict[str, Any]) -> dict[str, Any]:
    config = _load_settings()
    storage_root = (
        os.environ.get("CODEX_DURABLE_LEDGER_STORAGE_ROOT", "").strip()
        or str(config.get("storageRoot") or "").strip()
        or str(DEFAULT_STORAGE_ROOT)
    )
    namespace_override = (
        os.environ.get("CODEX_DURABLE_LEDGER_NAMESPACE", "").strip()
        or str(config.get("namespace") or DEFAULT_NAMESPACE_OVERRIDE).strip()
    )
    cwd = str(payload.get("cwd") or os.getcwd())
    workspace_root = _workspace_root(cwd)
    namespace = namespace_override or _default_namespace(workspace_root)
    return {
        "storage_root": Path(storage_root).expanduser(),
        "namespace": _sanitize_namespace(namespace),
        "workspace_root": workspace_root,
        "cwd": cwd,
    }


def _default_namespace(workspace_root: Path) -> str:
    label = workspace_root.name.strip() or "workspace"
    digest = hashlib.sha1(str(workspace_root).encode("utf-8")).hexdigest()[:8]
    return _sanitize_namespace(f"{label}-{digest}")


def _namespace_dir(settings: dict[str, Any]) -> Path:
    return Path(settings["storage_root"]) / "v1" / "namespaces" / settings["namespace"]


def _ensure_namespace_files(namespace_dir: Path) -> None:
    namespace_dir.mkdir(parents=True, exist_ok=True)
    for file_name in TABLE_FILES:
        path = namespace_dir / file_name
        if not path.exists():
            path.touch()


def _latest_record(path: Path, key: str, value: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for record in _iter_jsonl(path):
        if str(record.get(key) or "") == value:
            latest = record
    return latest


def _latest_record_where(path: Path, predicate) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for record in _iter_jsonl(path):
        if predicate(record):
            latest = record
    return latest


def _append_workspace(context: dict[str, Any]) -> None:
    path = context["namespace_dir"] / "workspaces.jsonl"
    existing = _latest_record(path, "id", context["workspace_id"])
    _append_jsonl(
        path,
        {
            "id": context["workspace_id"],
            "root": str(context["workspace_root"]),
            "created_at": existing.get("created_at") if existing else _now(),
        },
    )


def _append_agent(context: dict[str, Any]) -> None:
    path = context["namespace_dir"] / "agents.jsonl"
    existing = _latest_record(path, "id", context["agent_id"])
    _append_jsonl(
        path,
        {
            "id": context["agent_id"],
            "display_name": "Codex Durable Ledger",
            "workspace_id": context["workspace_id"],
            "created_at": existing.get("created_at") if existing else _now(),
        },
    )


def _append_thread(context: dict[str, Any], title: str) -> None:
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
                    "workspace_root": str(context["workspace_root"]),
                }
            ),
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
        },
    )


def _upsert_turn(context: dict[str, Any], turn_id: str, update: dict[str, Any]) -> None:
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


def _append_event(context: dict[str, Any], turn_id: str, kind: str, payload: dict[str, Any]) -> None:
    path = context["namespace_dir"] / "events.jsonl"
    sequence = 1
    for record in _iter_jsonl(path):
        if record.get("turn_id") == turn_id:
            sequence = max(sequence, int(record.get("sequence") or 0) + 1)
    _append_jsonl(
        path,
        {
            "id": _stable_id("event", turn_id, sequence, _now()),
            "turn_id": turn_id,
            "thread_id": context["thread_id"],
            "sequence": sequence,
            "kind": kind,
            "payload": _safe_json_dumps(payload),
            "created_at": _now(),
        },
    )


def _append_distill_state(context: dict[str, Any], turn_id: str | None, event_kind: str) -> None:
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


def _chunk_text(value: str, size: int = 1200) -> list[str]:
    text = value.strip()
    if not text:
        return []
    return [text[index : index + size] for index in range(0, len(text), size)]


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _thread_title(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input")
    tool_command = ""
    if isinstance(tool_input, dict):
        tool_command = str(tool_input.get("command") or "")
    candidate = str(
        payload.get("prompt")
        or payload.get("initialPrompt")
        or tool_command
        or "Codex session"
    ).strip()
    return candidate[:120] or "Codex session"


def _summary(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    return text[:240]


def _latest_wake_pack(namespace_dir: Path) -> str:
    path = namespace_dir / "wake-pack.md"
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8").strip()
        except Exception:
            text = ""
        if text:
            return text
    entries = _iter_jsonl(namespace_dir / "ledger_entries.jsonl")
    bullets: list[str] = []
    for record in entries[-DEFAULT_WINDOW:]:
        label = str(record.get("title") or record.get("entry_type") or "entry")
        summary = str(record.get("summary") or "").strip()
        if summary:
            bullets.append(f"- {label}: {summary}")
        else:
            bullets.append(f"- {label}")
    if not bullets:
        return DEFAULT_WAKE_PACK
    return "# Wake Pack\n\n" + "\n".join(bullets)


def _has_real_wake_pack(wake_pack: str) -> bool:
    return wake_pack.strip() != DEFAULT_WAKE_PACK


def _refresh_wake_pack(context: dict[str, Any]) -> str:
    wake_pack = _latest_wake_pack(context["namespace_dir"])
    _write_text(context["namespace_dir"] / "wake-pack.md", wake_pack + "\n")
    return wake_pack


def _context(settings: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    workspace_root = settings["workspace_root"]
    workspace_id = _stable_id("workspace", workspace_root)
    agent_id = _stable_id("agent", workspace_id, "codex")
    namespace_dir = _namespace_dir(settings)
    thread_id = str(payload.get("turn_id") or payload.get("session_id") or _stable_id("thread", workspace_id))
    return {
        "namespace": settings["namespace"],
        "namespace_dir": namespace_dir,
        "workspace_root": workspace_root,
        "workspace_id": workspace_id,
        "agent_id": agent_id,
        "thread_id": thread_id,
        "channel": "codex",
        "cwd": settings["cwd"],
    }


def _load_runtime_state(context: dict[str, Any]) -> dict[str, Any]:
    path = context["namespace_dir"] / ".runtime-state.json"
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_runtime_state(context: dict[str, Any], state: dict[str, Any]) -> None:
    path = context["namespace_dir"] / ".runtime-state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    state_to_write = dict(state)
    state_to_write["updated_at"] = _now()
    path.write_text(_safe_json_dumps(state_to_write), encoding="utf-8")


def _handle_session_start(settings: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(settings, payload)
    _ensure_namespace_files(context["namespace_dir"])
    _append_workspace(context)
    _append_agent(context)
    _append_thread(context, _thread_title(payload))
    wake_pack = _refresh_wake_pack(context)
    _append_distill_state(context, None, "session_start")
    _append_ledger_entry(
        context,
        entry_id=f"{context['thread_id']}:session_start",
        entry_type="trace_summary",
        source_type="session_start",
        source_id=context["thread_id"],
        turn_id=None,
        title="Session start",
        summary=_summary(str(payload.get("prompt") or payload.get("source") or "session start")),
        citation=context["thread_id"],
        payload={
            "event": "session_start",
            "source": payload.get("source"),
            "prompt": payload.get("prompt"),
            "permission_mode": payload.get("permission_mode"),
            "metadata": {"thread_id": context["thread_id"], "cwd": context["cwd"]},
        },
    )
    _write_runtime_state(
        context,
        {
            "session_id": str(payload.get("session_id") or context["thread_id"]),
            "thread_id": context["thread_id"],
            "current_turn_id": payload.get("turn_id"),
            "source": payload.get("source") or "startup",
            "started_at": _now(),
        },
    )
    if _has_real_wake_pack(wake_pack):
        return {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": wake_pack,
            },
        }
    return {"continue": True}


def _handle_user_prompt_submit(settings: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(settings, payload)
    _ensure_namespace_files(context["namespace_dir"])
    _append_workspace(context)
    _append_agent(context)
    _append_thread(context, _thread_title(payload))
    turn_id = str(payload.get("turn_id") or _stable_id("turn", context["thread_id"], payload.get("prompt") or _now()))
    prompt = str(payload.get("prompt") or "")
    _upsert_turn(
        context,
        turn_id,
        {
            "status": "open",
            "user_message": prompt,
            "assistant_message": None,
            "error": None,
        },
    )
    _append_event(
        context,
        turn_id,
        "user_turn",
        {
            "message": prompt,
            "metadata": {
                "thread_id": context["thread_id"],
                "cwd": context["cwd"],
                "permission_mode": payload.get("permission_mode"),
            },
        },
    )
    _append_ledger_entry(
        context,
        entry_id=f"{turn_id}:user",
        entry_type="user_turn",
        source_type="user_turn",
        source_id=turn_id,
        turn_id=turn_id,
        title="User turn",
        summary=_summary(prompt),
        citation=turn_id,
        payload={
            "content": prompt,
            "metadata": {
                "thread_id": context["thread_id"],
                "cwd": context["cwd"],
                "permission_mode": payload.get("permission_mode"),
            },
        },
    )
    _append_distill_state(context, turn_id, "user_turn")
    _write_runtime_state(
        context,
        {
            "session_id": str(payload.get("session_id") or context["thread_id"]),
            "thread_id": context["thread_id"],
            "current_turn_id": turn_id,
            "source": "prompt",
            "started_at": _load_runtime_state(context).get("started_at") or _now(),
        },
    )
    return {"continue": True}


def _handle_post_tool_use(settings: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(settings, payload)
    _ensure_namespace_files(context["namespace_dir"])
    _append_workspace(context)
    _append_agent(context)
    _append_thread(context, _thread_title(payload))
    turn_id = str(payload.get("turn_id") or _load_runtime_state(context).get("current_turn_id") or _stable_id("turn", context["thread_id"]))
    tool_name = str(payload.get("tool_name") or payload.get("tool_input", {}).get("name") or "Bash")
    tool_call_id = str(payload.get("tool_use_id") or payload.get("tool_call_id") or _stable_id("tool", turn_id, tool_name, _now()))
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    tool_response = payload.get("tool_response")
    if tool_response is None:
        tool_response = payload.get("tool_output")
    event_payload = {
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "tool_input": tool_input,
        "tool_response": tool_response,
        "metadata": {
            "thread_id": context["thread_id"],
            "cwd": context["cwd"],
        },
    }
    _append_event(context, turn_id, "tool_result", event_payload)
    _append_ledger_entry(
        context,
        entry_id=f"{turn_id}:tool_result:{tool_call_id}",
        entry_type="tool_result",
        source_type="tool_result",
        source_id=tool_call_id,
        turn_id=turn_id,
        title=f"Tool result: {tool_name}",
        summary=_summary(_safe_json_dumps(tool_response)) if tool_response is not None else None,
        citation=tool_call_id,
        payload=event_payload,
    )
    _append_distill_state(context, turn_id, "tool_result")
    _refresh_wake_pack(context)
    _write_runtime_state(
        context,
        {
            "session_id": str(payload.get("session_id") or context["thread_id"]),
            "thread_id": context["thread_id"],
            "current_turn_id": turn_id,
            "source": "tool",
            "started_at": _load_runtime_state(context).get("started_at") or _now(),
        },
    )
    return {"continue": True}


def _handle_stop(settings: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(settings, payload)
    _ensure_namespace_files(context["namespace_dir"])
    _append_workspace(context)
    _append_agent(context)
    _append_thread(context, _thread_title(payload))
    state = _load_runtime_state(context)
    turn_id = str(payload.get("turn_id") or state.get("current_turn_id") or context["thread_id"])
    _append_distill_state(context, turn_id, "session_end")
    _append_ledger_entry(
        context,
        entry_id=f"{context['thread_id']}:session_end",
        entry_type="trace_summary",
        source_type="session_end",
        source_id=context["thread_id"],
        turn_id=turn_id,
        title="Session end",
        summary="Session ended.",
        citation=context["thread_id"],
        payload={
            "event": "session_end",
            "metadata": {"thread_id": context["thread_id"], "cwd": context["cwd"]},
        },
    )
    _refresh_wake_pack(context)
    return {"continue": True}


def _handle_unknown(settings: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    context = _context(settings, payload)
    _ensure_namespace_files(context["namespace_dir"])
    _append_workspace(context)
    _append_agent(context)
    _append_thread(context, _thread_title(payload))
    return {"continue": True}


def main() -> int:
    payload = _read_payload()
    settings = _settings_for(payload)
    event_name = str(payload.get("hook_event_name") or "")
    if event_name == "SessionStart":
        output = _handle_session_start(settings, payload)
    elif event_name == "UserPromptSubmit":
        output = _handle_user_prompt_submit(settings, payload)
    elif event_name == "PostToolUse":
        output = _handle_post_tool_use(settings, payload)
    elif event_name == "Stop":
        output = _handle_stop(settings, payload)
    else:
        output = _handle_unknown(settings, payload)
    json.dump(output, sys.stdout, ensure_ascii=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
