#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import types

_HERE = Path(__file__).resolve().parent
_PKG_NAME = "hermes_adapter"
__path__ = [str(_HERE)]  # type: ignore[assignment]


def _load(name: str):
    fullname = f"{_PKG_NAME}.{name}"
    spec = importlib.util.spec_from_file_location(fullname, _HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


_shared = _load("_shared")
process = _load("process")
config = _load("config")
hooks = _load("hooks")
tools = _load("tools")
plugin = _load("plugin")

logger = _shared.logger
DEFAULT_NAMESPACE = _shared.DEFAULT_NAMESPACE

BeuProcess = process.BeuProcess
get_beu = process.get_beu

ledger_list_handler = tools.ledger_list_handler
ledger_search_handler = tools.ledger_search_handler
ledger_get_handler = tools.ledger_get_handler
beu_distill_handler = tools.beu_distill_handler

_resolve_namespace = hooks._resolve_namespace
_distill_threshold = hooks._distill_threshold
_note_hook = hooks._note_hook
_reset_hook_count = hooks._reset_hook_count
_trigger_backend_distill = hooks._trigger_backend_distill
_deep_merge_dicts = config._deep_merge_dicts
_beu_config_candidate_paths = config._beu_config_candidate_paths
_resolve_beu_config_path = config._resolve_beu_config_path
_read_beu_config_data = config._read_beu_config_data
_load_beu_config_file = config._load_beu_config_file
_collect_beu_embedding_settings = config._collect_beu_embedding_settings
_candidate_distill_payloads = config._candidate_distill_payloads
_index_entry = hooks._index_entry
_resolve_embedding_provider = config._resolve_embedding_provider
pre_llm_call_hook = hooks.pre_llm_call_hook
post_llm_call_hook = hooks.post_llm_call_hook
post_tool_call_hook = hooks.post_tool_call_hook
on_session_start_hook = hooks.on_session_start_hook
on_session_end_hook = hooks.on_session_end_hook


def register(ctx) -> None:
    plugin.register(
        ctx,
        api=types.SimpleNamespace(
            ledger_list_handler=ledger_list_handler,
            ledger_search_handler=ledger_search_handler,
            ledger_get_handler=ledger_get_handler,
            pre_llm_call_hook=pre_llm_call_hook,
            post_llm_call_hook=post_llm_call_hook,
            post_tool_call_hook=post_tool_call_hook,
            on_session_start_hook=on_session_start_hook,
            on_session_end_hook=on_session_end_hook,
        ),
    )


_ROOT_EXPORTS = types.SimpleNamespace(
    get_beu=lambda: get_beu(),
    _collect_beu_embedding_settings=lambda: _collect_beu_embedding_settings(),
    _index_entry=lambda **kwargs: _index_entry(**kwargs),
    _resolve_embedding_provider=lambda **kwargs: _resolve_embedding_provider(**kwargs),
)


def _bind_root_exports() -> None:
    config._ROOT = _ROOT_EXPORTS
    hooks._ROOT = _ROOT_EXPORTS
    tools._ROOT = _ROOT_EXPORTS


_bind_root_exports()
