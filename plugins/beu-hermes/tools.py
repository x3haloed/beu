from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import DELTA_PATH, normalize_delta, validate_state_delta


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
            "add_recent",
            "set_next",
        )
        if args.get(key) is not None
    }
    path = append_state_delta(delta)
    return f"Appended delta to {path}"
