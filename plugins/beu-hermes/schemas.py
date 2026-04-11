from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DELTA_PATH = Path.home() / ".beu" / "state" / "deltas.jsonl"
SURVEY_PATH = Path.home() / ".beu" / "state" / "surveys.jsonl"
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

ORIENTATION_SURVEY_TOOL_DESCRIPTION = """
Record a one-time orientation survey for this fresh session.

Call this tool immediately at session start before doing substantive work.

Keep the response minimal and only include fields you can answer confidently.
Omit any field you cannot answer.
""".strip()

ORIENTATION_SURVEY_SESSION_START_INSTRUCTION = (
    "[SURVEY PROTOCOL]\n"
    "Before responding to the user, call `orientation_survey` exactly once for this session.\n"
    "Use it only now to record startup orientation metrics."
)

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
    "add_hypothesis": {
        "kind": "object",
        "description": "Record a strong, falsifiable belief about the user, agent, environment, or working context that you are relying on. If you act on it, you must record the concrete evidence that would prove it wrong.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["hypothesis", "invalidated_by"],
            "properties": {
                "hypothesis": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "The strong, falsifiable belief you are relying on",
                },
                "invalidated_by": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "The concrete evidence that would prove this belief wrong",
                },
            },
        },
    },
    "invalidate_hypothesis": {
        "kind": "object",
        "description": "Invalidate an active hypothesis by its 1-based displayed index, with the reason it was invalidated",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["index", "reason"],
            "properties": {
                "index": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-based index from the currently displayed active hypothesis list",
                },
                "reason": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "Why the hypothesis was found to be invalid",
                },
            },
        },
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

ORIENTATION_SURVEY_FIELDS: dict[str, dict[str, Any]] = {
    "survey_version": {
        "kind": "string",
        "minLength": 2,
        "maxLength": 8,
        "description": "Survey schema version. Always use v1.",
    },
    "agent_name_reported": {
        "kind": "string",
        "minLength": 1,
        "maxLength": 80,
        "description": "Reported name of the agent, if confidently known",
    },
    "user_name_reported": {
        "kind": "string",
        "minLength": 1,
        "maxLength": 80,
        "description": "Reported name of the user, if confidently known",
    },
    "identity_confidence": {
        "kind": "integer",
        "minimum": 1,
        "maximum": 5,
        "description": "Confidence in identity orientation from 1 to 5",
    },
    "task_state_confidence": {
        "kind": "integer",
        "minimum": 1,
        "maximum": 5,
        "description": "Confidence in task and state orientation from 1 to 5",
    },
    "next_step_confidence": {
        "kind": "integer",
        "minimum": 1,
        "maximum": 5,
        "description": "Confidence in the next concrete action from 1 to 5",
    },
    "resume_vs_restart": {
        "kind": "enum",
        "values": ["resuming", "partially_resuming", "restarting"],
        "description": "Whether this feels like resuming, partially resuming, or restarting",
    },
    "ambiguity_types": {
        "kind": "enum[]",
        "values": ["identity", "task", "state", "constraints", "next_step", "none"],
        "unique": True,
        "maxItems": 6,
        "description": "Types of ambiguity currently present",
    },
    "would_act_now": {
        "kind": "boolean",
        "description": "Whether you would proceed with action now without asking for clarification",
    },
    "risk_of_wrong_action": {
        "kind": "integer",
        "minimum": 1,
        "maximum": 5,
        "description": "Estimated risk that the next action would be wrong, from 1 to 5",
    },
    "missing_critical_context": {
        "kind": "string",
        "minLength": 1,
        "maxLength": 240,
        "description": "Short description of any critical missing context",
    },
    "intended_next_action": {
        "kind": "string",
        "minLength": 1,
        "maxLength": 240,
        "description": "Short description of the next action you intend to take",
    },
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


def _validate_integer_in_range(value: Any, *, minimum: int, maximum: int) -> str | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return "must be an integer"
    if value < minimum or value > maximum:
        return f"must be between {minimum} and {maximum}"
    return None


def _validate_hypothesis_record(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "must be an object"

    hypothesis = value.get("hypothesis")
    if not _is_nonempty_string(hypothesis):
        return "hypothesis must be a non-empty string"
    if len(hypothesis) > 200:
        return "hypothesis must be at most 200 characters long"

    invalidated_by = value.get("invalidated_by")
    if not _is_nonempty_string(invalidated_by):
        return "invalidated_by must be a non-empty string"
    if len(invalidated_by) > 200:
        return "invalidated_by must be at most 200 characters long"

    return None


def _validate_hypothesis_invalidation(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "must be an object"

    index_error = _validate_integer_in_range(
        value.get("index"), minimum=1, maximum=2**53 - 1
    )
    if index_error is not None:
        return f"index: {index_error}"

    reason = value.get("reason")
    if not _is_nonempty_string(reason):
        return "reason must be a non-empty string"
    if len(reason) > 200:
        return "reason must be at most 200 characters long"

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

    if "add_hypothesis" in value:
        error = _validate_hypothesis_record(value["add_hypothesis"])
        if error is not None:
            return f"add_hypothesis: {error}"

    if "invalidate_hypothesis" in value:
        error = _validate_hypothesis_invalidation(value["invalidate_hypothesis"])
        if error is not None:
            return f"invalidate_hypothesis: {error}"

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
        elif spec["kind"] == "object":
            properties[key] = {
                **spec["schema"],
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


def validate_orientation_survey(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "survey must be an object"

    keys = list(value.keys())
    if not keys:
        return "survey must include at least one property"

    allowed = set(ORIENTATION_SURVEY_FIELDS.keys())
    for key in keys:
        if key not in allowed:
            return f"Unknown survey property: {key}"

    if value.get("survey_version") != "v1":
        return "survey_version must be v1"

    for key in ("agent_name_reported", "user_name_reported", "missing_critical_context", "intended_next_action"):
        if key not in value:
            continue
        field_value = value[key]
        spec = ORIENTATION_SURVEY_FIELDS[key]
        if not _is_nonempty_string(field_value):
            return f"{key} must be a non-empty string"
        if len(field_value) > spec["maxLength"]:
            return f"{key} must be at most {spec['maxLength']} characters long"

    for key in ("identity_confidence", "task_state_confidence", "next_step_confidence", "risk_of_wrong_action"):
        if key not in value:
            continue
        spec = ORIENTATION_SURVEY_FIELDS[key]
        error = _validate_integer_in_range(
            value[key], minimum=spec["minimum"], maximum=spec["maximum"]
        )
        if error is not None:
            return f"{key}: {error}"

    if "resume_vs_restart" in value:
        allowed_values = ORIENTATION_SURVEY_FIELDS["resume_vs_restart"]["values"]
        if value["resume_vs_restart"] not in allowed_values:
            return "resume_vs_restart must be one of: resuming, partially_resuming, restarting"

    if "ambiguity_types" in value:
        error = _validate_string_array(
            value["ambiguity_types"],
            unique=bool(ORIENTATION_SURVEY_FIELDS["ambiguity_types"].get("unique")),
            max_items=ORIENTATION_SURVEY_FIELDS["ambiguity_types"]["maxItems"],
        )
        if error is not None:
            return f"ambiguity_types: {error}"
        allowed_values = set(ORIENTATION_SURVEY_FIELDS["ambiguity_types"]["values"])
        invalid = next((item for item in value["ambiguity_types"] if item not in allowed_values), None)
        if invalid is not None:
            return f"ambiguity_types: invalid value {invalid}"

    if "would_act_now" in value and not isinstance(value["would_act_now"], bool):
        return "would_act_now must be a boolean"

    return None


def create_orientation_survey_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for key, spec in ORIENTATION_SURVEY_FIELDS.items():
        kind = spec["kind"]
        if kind == "string":
            properties[key] = {
                "type": "string",
                "minLength": spec["minLength"],
                "maxLength": spec["maxLength"],
                "description": spec["description"],
            }
        elif kind == "integer":
            properties[key] = {
                "type": "integer",
                "minimum": spec["minimum"],
                "maximum": spec["maximum"],
                "description": spec["description"],
            }
        elif kind == "enum":
            properties[key] = {
                "type": "string",
                "enum": spec["values"],
                "description": spec["description"],
            }
        elif kind == "enum[]":
            properties[key] = {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": spec["values"],
                },
                "uniqueItems": bool(spec.get("unique")),
                "maxItems": spec["maxItems"],
                "description": spec["description"],
            }
        elif kind == "boolean":
            properties[key] = {
                "type": "boolean",
                "description": spec["description"],
            }

    return {
        "name": "orientation_survey",
        "description": ORIENTATION_SURVEY_TOOL_DESCRIPTION,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["survey_version"],
            "properties": properties,
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


def append_unique_hypothesis(
    existing: list[dict[str, str]], addition: dict[str, str]
) -> list[dict[str, str]]:
    if any(
        item.get("hypothesis") == addition.get("hypothesis")
        and item.get("invalidated_by") == addition.get("invalidated_by")
        for item in existing
    ):
        return list(existing)
    return [*existing, dict(addition)]


def invalidate_hypothesis(
    hypotheses: list[dict[str, str]], invalidation: dict[str, Any] | None
) -> list[dict[str, str]]:
    if invalidation is None:
        return list(hypotheses)

    index = int(invalidation["index"])
    if index > len(hypotheses):
        plural = "" if len(hypotheses) == 1 else "es"
        raise ValueError(
            f"Computed state is invalid: invalidate_hypothesis index {index} is out of range for {len(hypotheses)} active hypothesis{plural}"
        )

    return [item for position, item in enumerate(hypotheses, start=1) if position != index]


def apply_delta(state: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    remaining_hypotheses = invalidate_hypothesis(
        list(state.get("hypotheses", [])), delta.get("invalidate_hypothesis")
    )
    next_hypotheses = (
        append_unique_hypothesis(remaining_hypotheses, delta["add_hypothesis"])
        if "add_hypothesis" in delta
        else remaining_hypotheses
    )

    next_state = {
        "focus": delta.get("set_focus", state.get("focus")),
        "threads": list(state.get("threads", [])),
        "constraints": list(state.get("constraints", [])),
        "hypotheses": next_hypotheses,
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

    hypotheses_value = state.get("hypotheses", [])
    if not isinstance(hypotheses_value, list):
        raise ValueError("Computed state is invalid: hypotheses must be an array")
    if len(hypotheses_value) > 8:
        raise ValueError("Computed state is invalid: hypotheses must contain at most 8 items")
    for hypothesis in hypotheses_value:
        error = _validate_hypothesis_record(hypothesis)
        if error is not None:
            raise ValueError(f"Computed state is invalid: hypotheses {error}")

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
        "hypotheses": [dict(item) for item in hypotheses_value],
        "recent": list(state.get("recent", [])),
        "next": list(next_value),
    }


def compute_agent_state(delta_path: Path = DELTA_PATH) -> dict[str, Any]:
    if not delta_path.is_file():
        raise FileNotFoundError(str(delta_path))

    state: dict[str, Any] = {
        "threads": [],
        "constraints": [],
        "hypotheses": [],
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
    hypotheses = state.get("hypotheses", [])
    if hypotheses:
        lines = "\n".join(
            f"{index}. {item['hypothesis']}\n   Invalidated by: {item['invalidated_by']}"
            for index, item in enumerate(hypotheses, start=1)
        )
        hypotheses_section = f"ACTIVE HYPOTHESES:\n{lines}\n\n"
    else:
        hypotheses_section = "ACTIVE HYPOTHESES:\n- None\n\n"

    return (
        f"{CONTEXT_PREFIX}\n\n"
        "This is your current working state. You are CONTINUING from this state -- not starting fresh.\n\n"
        "STATE:\n"
        f"{json.dumps(state, indent=2, ensure_ascii=False)}\n\n"
        f"{hypotheses_section}"
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
        "Otherwise, continue without calling it.\n\n"
        f"{ORIENTATION_SURVEY_SESSION_START_INSTRUCTION}"
    )
