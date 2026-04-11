from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import (
    DELTA_PATH,
    SURVEY_PATH,
    normalize_delta,
    validate_orientation_survey,
    validate_state_delta,
)


def append_state_delta(delta: dict[str, Any], delta_path: Path = DELTA_PATH) -> Path:
    normalized = normalize_delta(delta)
    validation_error = validate_state_delta(normalized)
    if validation_error is not None:
        raise ValueError(validation_error)

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
