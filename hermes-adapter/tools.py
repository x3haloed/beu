from __future__ import annotations

import json

from ._shared import DEFAULT_NAMESPACE
from .hooks import _resolve_namespace


_ROOT = None


def ledger_list_handler(args: dict, **kw) -> str:
    namespace = _resolve_namespace(kw)
    try:
        result = _ROOT.get_beu().call(
            "ledger_list",
            {
                "namespace": namespace,
                "thread_id": args.get("thread_id"),
                "kind": args.get("kind"),
                "limit": int(args.get("limit", 20) or 20),
            },
        )
        return json.dumps(result.get("data", {}), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def ledger_search_handler(args: dict, **kw) -> str:
    namespace = _resolve_namespace(kw)
    query = args.get("query", "")
    if not query:
        return json.dumps({"error": "query is required"})
    try:
        result = _ROOT.get_beu().call(
            "ledger_search",
            {
                "namespace": namespace,
                "query": query,
                "thread_id": args.get("thread_id"),
                "kind": args.get("kind"),
                "limit": int(args.get("limit", 8) or 8),
            },
        )
        return json.dumps(result.get("data", {}), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def ledger_get_handler(args: dict, **kw) -> str:
    namespace = _resolve_namespace(kw)
    entry_id = args.get("entry_id", "")
    if not entry_id:
        return json.dumps({"error": "entry_id is required"})
    try:
        result = _ROOT.get_beu().call("ledger_get", {"namespace": namespace, "entry_id": entry_id})
        if not result.get("ok"):
            return json.dumps({"error": result.get("error", f"ledger entry not found: {entry_id}")})
        return json.dumps(result.get("data", {}), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def beu_distill_handler(args: dict, **kw) -> str:
    beu = _ROOT.get_beu()
    thread_id = args.get("thread_id", "")
    turn_id = args.get("turn_id", "")
    namespace = args.get("namespace", DEFAULT_NAMESPACE)
    if not thread_id or not turn_id:
        return json.dumps({"success": False, "error": "thread_id and turn_id are required"})
    result = beu.distill(
        {
            "thread_id": thread_id,
            "turn_id": turn_id,
            "provider": args.get("provider"),
            "model": args.get("model"),
            "base_url": args.get("base_url"),
            "api_key": args.get("api_key"),
            "limit": int(args.get("limit", 48) or 48),
        },
        namespace=namespace,
    )
    if not result:
        return json.dumps({"success": False, "error": "Distillation failed"})
    return json.dumps({"success": True, "result": result}, ensure_ascii=False)
