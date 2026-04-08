from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DELTA_PATH = Path.home() / ".beu" / "state" / "deltas.jsonl"
CONTEXT_PREFIX = "[BEU STATE]"
DELTA_TOOL_DESCRIPTION = """
Persist a minimal state update when orientation changes.

CALL THIS TOOL IMMEDIATELY if:
- Focus changes or sharpens
- A new thread appears or a thread is resolved
- A constraint is discovered
- A meaningful step completes
- Next actions change

DO NOT call for explanation or minor reasoning.

CRITICAL:
If failing to record this change would cause the next step to go in the wrong direction,
you MUST call delta().
""".strip()

STATE_DELTA_FIELDS: dict[str, dict[str, Any]] = {
    "set_focus": {
        "kind": "string",
        "minLength": 1,
        "maxLength": 200,
        "description": "Replace the current focus with a new one",
    },
    "add_threads": {
        "kind": "string[]",
        "itemMinLength": 1,
        "itemMaxLength": 160,
        "unique": True,
        "description": "Add new active threads",
    },
    "remove_threads": {
        "kind": "string[]",
        "itemMinLength": 1,
        "itemMaxLength": 160,
        "unique": True,
        "description": "Remove completed or irrelevant threads",
    },
    "add_constraints": {
        "kind": "string[]",
        "itemMinLength": 1,
        "itemMaxLength": 200,
        "unique": True,
        "description": "Add newly discovered constraints or invariants",
    },
    "add_recent": {
        "kind": "string[]",
        "itemMinLength": 1,
        "itemMaxLength": 200,
        "maxItems": 5,
        "description": "Append recent meaningful steps (will be truncated in state)",
    },
    "set_next": {
        "kind": "string[]",
        "itemMinLength": 1,
        "itemMaxLength": 160,
        "minItems": 1,
        "description": "Replace next actions list",
    },
}

STATE_DELTA_FIELD_DESCRIPTIONS = {
    key: spec["description"] for key, spec in STATE_DELTA_FIELDS.items()
}


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _validate_string_array(
    value: Any,
    *,
    unique: bool = False,
    min_items: int | None = None,
    max_items: int | None = None,
    max_length: int | None = None,
) -> str | None:
    if not isinstance(value, list):
        return "must be an array of strings"

    if min_items is not None and len(value) < min_items:
        plural = "" if min_items == 1 else "s"
        return f"must contain at least {min_items} item{plural}"

    if max_items is not None and len(value) > max_items:
        plural = "" if max_items == 1 else "s"
        return f"must contain at most {max_items} item{plural}"

    seen: set[str] = set()
    for item in value:
        if not _is_nonempty_string(item):
            return "must contain only non-empty strings"
        if max_length is not None and len(item) > max_length:
            return f"items must be at most {max_length} characters long"
        if unique:
            if item in seen:
                return "must not contain duplicate values"
            seen.add(item)

    return None


def validate_state_delta(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "delta must be an object"

    value = normalize_delta(value)
    keys = list(value.keys())
    if not keys:
        return "delta must include at least one property"

    allowed = set(STATE_DELTA_FIELDS.keys())
    for key in keys:
        if key not in allowed:
            return f"Unknown delta property: {key}"

    if "set_focus" in value:
        focus = value["set_focus"]
        if not _is_nonempty_string(focus):
            return "set_focus must be a non-empty string"
        if len(focus) > STATE_DELTA_FIELDS["set_focus"]["maxLength"]:
            return f"set_focus must be at most {STATE_DELTA_FIELDS['set_focus']['maxLength']} characters long"

    if "add_threads" in value:
        error = _validate_string_array(
            value["add_threads"],
            unique=bool(STATE_DELTA_FIELDS["add_threads"].get("unique")),
            max_length=STATE_DELTA_FIELDS["add_threads"]["itemMaxLength"],
        )
        if error is not None:
            return f"add_threads: {error}"

    if "remove_threads" in value:
        error = _validate_string_array(
            value["remove_threads"],
            unique=bool(STATE_DELTA_FIELDS["remove_threads"].get("unique")),
            max_length=STATE_DELTA_FIELDS["remove_threads"]["itemMaxLength"],
        )
        if error is not None:
            return f"remove_threads: {error}"

    if "add_constraints" in value:
        error = _validate_string_array(
            value["add_constraints"],
            unique=bool(STATE_DELTA_FIELDS["add_constraints"].get("unique")),
            max_length=STATE_DELTA_FIELDS["add_constraints"]["itemMaxLength"],
        )
        if error is not None:
            return f"add_constraints: {error}"

    if "add_recent" in value:
        error = _validate_string_array(
            value["add_recent"],
            max_items=STATE_DELTA_FIELDS["add_recent"]["maxItems"],
            max_length=STATE_DELTA_FIELDS["add_recent"]["itemMaxLength"],
        )
        if error is not None:
            return f"add_recent: {error}"

    if "set_next" in value:
        error = _validate_string_array(
            value["set_next"],
            min_items=STATE_DELTA_FIELDS["set_next"]["minItems"],
            max_length=STATE_DELTA_FIELDS["set_next"]["itemMaxLength"],
        )
        if error is not None:
            return f"set_next: {error}"

    return None


def create_state_delta_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for key, spec in STATE_DELTA_FIELDS.items():
        if spec["kind"] == "string":
            properties[key] = {
                "type": "string",
                "minLength": spec["minLength"],
                "maxLength": spec["maxLength"],
                "description": spec["description"],
            }
        else:
            string_schema = {
                "type": "string",
                "minLength": spec["itemMinLength"],
                "maxLength": spec["itemMaxLength"],
            }
            schema = {
                "type": "array",
                "items": string_schema,
                "description": spec["description"],
            }
            if spec.get("unique"):
                schema["uniqueItems"] = True
            if "minItems" in spec:
                schema["minItems"] = spec["minItems"]
            if "maxItems" in spec:
                schema["maxItems"] = spec["maxItems"]
            properties[key] = {
                "anyOf": [string_schema, schema],
                "description": spec["description"],
            }

    return {
        "name": "delta",
        "description": DELTA_TOOL_DESCRIPTION,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "minProperties": 1,
        },
    }


def normalize_delta(value: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if item is None:
            continue
        spec = STATE_DELTA_FIELDS.get(key)
        if spec is not None and spec["kind"] == "string[]" and isinstance(item, str):
            normalized[key] = [item]
        else:
            normalized[key] = item
    return normalized


def append_unique(existing: list[str], additions: list[str]) -> list[str]:
    next_values = list(existing)
    seen = set(existing)
    for item in additions:
        if item not in seen:
            next_values.append(item)
            seen.add(item)
    return next_values


def apply_delta(state: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    next_state = {
        "focus": delta.get("set_focus", state.get("focus")),
        "threads": list(state.get("threads", [])),
        "constraints": list(state.get("constraints", [])),
        "recent": list(state.get("recent", [])),
        "next": list(state.get("next", [])) if state.get("next") is not None else None,
    }

    if "remove_threads" in delta:
        next_state["threads"] = append_unique(next_state["threads"], delta.get("add_threads", []))
        removed = set(delta.get("remove_threads", []))
        next_state["threads"] = [thread for thread in next_state["threads"] if thread not in removed]
    elif "add_threads" in delta:
        next_state["threads"] = append_unique(next_state["threads"], delta.get("add_threads", []))

    if "add_constraints" in delta:
        next_state["constraints"] = append_unique(next_state["constraints"], delta.get("add_constraints", []))

    if "add_recent" in delta:
        next_state["recent"] = (next_state["recent"] + list(delta.get("add_recent", [])))[-5:]

    if "set_next" in delta:
        next_state["next"] = list(delta.get("set_next", []))

    return next_state


def validate_final_state(state: dict[str, Any]) -> dict[str, Any]:
    focus = state.get("focus")
    if not _is_nonempty_string(focus):
        raise ValueError("Computed state is invalid: focus is required")
    if len(focus) > 200:
        raise ValueError("Computed state is invalid: focus must be at most 200 characters long")

    threads_error = _validate_string_array(
        state.get("threads", []), unique=True, max_items=8, max_length=160
    )
    if threads_error is not None:
        raise ValueError(f"Computed state is invalid: threads {threads_error}")

    constraints_error = _validate_string_array(
        state.get("constraints", []), unique=True, max_items=8, max_length=200
    )
    if constraints_error is not None:
        raise ValueError(f"Computed state is invalid: constraints {constraints_error}")

    recent_error = _validate_string_array(state.get("recent", []), max_items=5, max_length=200)
    if recent_error is not None:
        raise ValueError(f"Computed state is invalid: recent {recent_error}")

    next_value = state.get("next")
    if next_value is None:
        raise ValueError("Computed state is invalid: next is required")

    next_error = _validate_string_array(next_value, min_items=1, max_items=5, max_length=160)
    if next_error is not None:
        raise ValueError(f"Computed state is invalid: next {next_error}")

    return {
        "focus": focus,
        "threads": list(state.get("threads", [])),
        "constraints": list(state.get("constraints", [])),
        "recent": list(state.get("recent", [])),
        "next": list(next_value),
    }


def compute_agent_state(delta_path: Path = DELTA_PATH) -> dict[str, Any]:
    if not delta_path.is_file():
        raise FileNotFoundError(str(delta_path))

    state: dict[str, Any] = {
        "threads": [],
        "constraints": [],
        "recent": [],
    }

    for line_no, raw_line in enumerate(delta_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid JSON in {delta_path} at line {line_no}: {exc}") from exc

        parsed = normalize_delta(parsed)
        validation_error = validate_state_delta(parsed)
        if validation_error is not None:
            raise ValueError(f"Invalid delta in {delta_path} at line {line_no}: {validation_error}")

        state = apply_delta(state, parsed)

    return validate_final_state(state)


def format_state_context(state: dict[str, Any]) -> str:
    return (
        f"{CONTEXT_PREFIX}\n\n"
        "This is your current working state. You are CONTINUING from this state -- not starting fresh.\n\n"
        "STATE:\n"
        f"{json.dumps(state, indent=2, ensure_ascii=False)}\n\n"
        "You MUST maintain this state as you work.\n\n"
        "Call the delta tool IMMEDIATELY if any of the following become true:\n"
        "- The focus changes or sharpens\n"
        "- A new thread appears\n"
        "- A thread is resolved or irrelevant\n"
        "- A constraint is discovered\n"
        "- A meaningful step completes\n"
        "- The next actions change\n\n"
        "Do NOT call delta for minor reasoning or explanation.\n\n"
        "If failing to update this state would cause future steps to go in the wrong direction,\n"
        "you MUST call delta.\n\n"
        "Otherwise, continue without calling it."
    )
