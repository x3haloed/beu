#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from store import CopilotCliLedgerStore, load_settings


def _read_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    loaded = json.loads(raw)
    return loaded if isinstance(loaded, dict) else {}


def main() -> int:
    if len(sys.argv) != 2:
        return 1
    event_name = sys.argv[1]
    payload = _read_payload()
    settings = load_settings(payload.get("cwd") if isinstance(payload, dict) else None)
    store = CopilotCliLedgerStore(settings)

    if event_name == "session-start":
        store.handle_session_start(payload)
    elif event_name == "user-prompt-submitted":
        store.handle_user_prompt_submitted(payload)
    elif event_name == "pre-tool-use":
        store.handle_pre_tool_use(payload)
    elif event_name == "post-tool-use":
        store.handle_post_tool_use(payload)
    elif event_name == "error-occurred":
        store.handle_error_occurred(payload)
    elif event_name == "session-end":
        store.handle_session_end(payload)
    else:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())