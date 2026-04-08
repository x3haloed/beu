from __future__ import annotations

from .schemas import (
    DELTA_TOOL_DESCRIPTION,
    ORIENTATION_SURVEY_TOOL_DESCRIPTION,
    compute_agent_state,
    create_orientation_survey_schema,
    create_state_delta_schema,
    format_state_context,
)
from .tools import handle_delta, handle_orientation_survey

_INJECTED_SESSIONS: set[str] = set()


def _inject_state_for_turn(**kwargs):
    session_id = str(kwargs.get("session_id") or "")
    is_first_turn = bool(kwargs.get("is_first_turn"))
    if not is_first_turn or not session_id or session_id in _INJECTED_SESSIONS:
        return None

    _INJECTED_SESSIONS.add(session_id)

    try:
        state = compute_agent_state()
    except FileNotFoundError:
        return None
    except Exception:
        return None

    return {"context": format_state_context(state)}


def _mark_session_start(**kwargs):
    session_id = str(kwargs.get("session_id") or "")
    if session_id:
        _INJECTED_SESSIONS.discard(session_id)


def _mark_session_end(**kwargs):
    session_id = str(kwargs.get("session_id") or "")
    if session_id:
        _INJECTED_SESSIONS.discard(session_id)


def register(ctx):
    ctx.register_tool("delta", "beu", create_state_delta_schema(), handle_delta, description=DELTA_TOOL_DESCRIPTION)
    ctx.register_tool(
        "orientation_survey",
        "beu",
        create_orientation_survey_schema(),
        handle_orientation_survey,
        description=ORIENTATION_SURVEY_TOOL_DESCRIPTION,
    )
    ctx.register_hook("pre_llm_call", _inject_state_for_turn)
    ctx.register_hook("on_session_start", _mark_session_start)
    ctx.register_hook("on_session_end", _mark_session_end)
