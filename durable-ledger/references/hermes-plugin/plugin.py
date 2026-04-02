from __future__ import annotations

from ._shared import logger
from .config import load_settings
from .store import JsonlLedgerStore


_STORE = JsonlLedgerStore(load_settings())


def pre_llm_call_hook(**kwargs):
    _STORE.pre_llm_call(dict(kwargs))
    return None


def post_llm_call_hook(**kwargs):
    _STORE.post_llm_call(dict(kwargs))
    return None


def post_tool_call_hook(tool_name, args, result, task_id=None, **kwargs):
    _STORE.post_tool_call(tool_name, args, result, task_id, **kwargs)
    return None


def on_session_start_hook(**kwargs):
    _STORE.on_session_start(dict(kwargs))
    return None


def on_session_end_hook(**kwargs):
    _STORE.on_session_end(dict(kwargs))
    return None


def register(ctx, *, api=None) -> None:
    logger.info("Registering durable-ledger Hermes plugin")
    ctx.register_hook("pre_llm_call", pre_llm_call_hook)
    ctx.register_hook("post_llm_call", post_llm_call_hook)
    ctx.register_hook("post_tool_call", post_tool_call_hook)
    ctx.register_hook("on_session_start", on_session_start_hook)
    ctx.register_hook("on_session_end", on_session_end_hook)
    logger.info("Durable-ledger Hermes plugin registered")