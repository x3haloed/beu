from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import (
    DELTA_PATH,
    SURVEY_PATH,
    THREAD_LIMIT,
    normalize_delta,
    append_unique,
    compute_agent_state,
    validate_orientation_survey,
    validate_state_delta,
)


def apply_thread_delta(threads: list[str], delta: dict[str, Any]) -> list[str]:
    if "remove_threads" in delta:
        updated = append_unique(threads, delta.get("add_threads", []))
        removed = set(delta.get("remove_threads", []))
        return [thread for thread in updated if thread not in removed]
    if "add_threads" in delta:
        return append_unique(threads, delta.get("add_threads", []))
    return list(threads)


def append_state_delta(delta: dict[str, Any], delta_path: Path = DELTA_PATH) -> Path:
    normalized = normalize_delta(delta)
    validation_error = validate_state_delta(normalized)
    if validation_error is not None:
        raise ValueError(validation_error)

    current_state = {
        "threads": [],
        "constraints": [],
        "hypotheses": [],
        "recent": [],
    }
    if delta_path.exists():
        # Reconstruct the live state so we can write explicit thread removals when needed.
        current_state = compute_agent_state(delta_path)

    next_threads = apply_thread_delta(list(current_state.get("threads", [])), normalized)
    overflow = max(0, len(next_threads) - THREAD_LIMIT)
    if overflow > 0:
        normalized = {
            **normalized,
            "remove_threads": append_unique(
                list(normalized.get("remove_threads", [])),
                next_threads[:overflow],
            ),
        }

    delta_path.parent.mkdir(parents=True, exist_ok=True)
    with delta_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(normalized, ensure_ascii=False) + "\n")
    return delta_path


def handle_delta(args: dict[str, Any], **_: Any) -> str:
    delta = {
        key: args.get(key)
        for key in (
            "set_focus",
            "add_threads",
            "remove_threads",
            "add_constraints",
            "add_hypothesis",
            "invalidate_hypothesis",
            "add_recent",
            "set_next",
        )
        if args.get(key) is not None
    }
    path = append_state_delta(delta)
    return f"Appended delta to {path}"


def append_constraint_compression(constraint: str, delta_path: Path = DELTA_PATH) -> Path:
    if not isinstance(constraint, str) or len(constraint) == 0:
        raise ValueError("constraint must be a non-empty string")
    if len(constraint) > 200:
        raise ValueError("constraint must be at most 200 characters long")

    state = compute_agent_state(delta_path) if delta_path.exists() else {"constraints": []}
    delta = {
        "remove_constraints": list(state.get("constraints", [])),
        "add_constraints": [constraint],
    }
    validation_error = validate_state_delta(delta)
    if validation_error is not None:
        raise ValueError(validation_error)

    delta_path.parent.mkdir(parents=True, exist_ok=True)
    with delta_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(delta, ensure_ascii=False) + "\n")
    return delta_path


def append_hypothesis_compression(hypothesis: str, delta_path: Path = DELTA_PATH) -> Path:
    if not isinstance(hypothesis, str) or len(hypothesis) == 0:
        raise ValueError("hypothesis must be a non-empty string")
    if len(hypothesis) > 200:
        raise ValueError("hypothesis must be at most 200 characters long")

    current_state = compute_agent_state(delta_path) if delta_path.exists() else {"hypotheses": []}
    lines = []
    for index in range(len(current_state.get("hypotheses", [])), 0, -1):
        lines.append(
            json.dumps(
                {
                    "invalidate_hypothesis": {
                        "index": index,
                        "reason": "Compressed into a single summary hypothesis.",
                    }
                },
                ensure_ascii=False,
            )
        )
    lines.append(
        json.dumps(
            {
                "add_hypothesis": {
                    "hypothesis": hypothesis,
                    "invalidated_by": "Evidence that the compressed summary no longer captures the active hypotheses.",
                }
            },
            ensure_ascii=False,
        )
    )

    delta_path.parent.mkdir(parents=True, exist_ok=True)
    with delta_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return delta_path


def append_orientation_survey(
    survey: dict[str, Any], survey_path: Path = SURVEY_PATH
) -> Path:
    validation_error = validate_orientation_survey(survey)
    if validation_error is not None:
        raise ValueError(validation_error)

    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **survey,
    }

    survey_path.parent.mkdir(parents=True, exist_ok=True)
    with survey_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return survey_path


def handle_orientation_survey(args: dict[str, Any], **_: Any) -> str:
    survey = {key: value for key, value in args.items() if value is not None}
    path = append_orientation_survey(survey)
    return f"Appended orientation survey to {path}"


def handle_compress(args: dict[str, Any], **_: Any) -> str:
    kind = args.get("kind")
    if kind == "constraint":
        path = append_constraint_compression(str(args.get("constraint") or ""))
        return f"Compressed constraints and appended to {path}"
    if kind == "hypothesis":
        path = append_hypothesis_compression(str(args.get("hypothesis") or ""))
        return f"Compressed hypotheses and appended to {path}"
    raise ValueError("compress requires kind=constraint or kind=hypothesis")
