#[path = "hermes_adapter_support.rs"]
mod hermes_adapter_support;

use hermes_adapter_support::hermes_harness;

#[test]
fn hermes_adapter_contract_is_clean_and_idempotent() {
    let harness = hermes_harness();
    let namespace = format!("contract-{}", uuid::Uuid::new_v4());

    let script = format!(
        r#"
import json
import os
import sys
from pathlib import Path

repo_root = Path(os.environ["BEU_HERMES_AGENT_REPO"])
sys.path.insert(0, str(repo_root))

from hermes_cli.plugins import get_plugin_manager

mgr = get_plugin_manager()
mgr.discover_and_load()
beu = mgr._plugins["beu"].module

empty_before = json.loads(beu.ledger_list_handler({{
    "namespace": "{namespace}",
    "thread_id": "{namespace}",
    "limit": 5
}}, session_key="{namespace}"))
if empty_before.get("entries") != []:
    raise SystemExit(json.dumps(empty_before))

beu.pre_llm_call_hook([], session_id="{namespace}", user_message="User prefers detailed explanations")
beu.post_llm_call_hook("Assistant acknowledges the preference.", [], session_id="{namespace}")
beu.post_tool_call_hook("beu_list", {{}}, {{"ok": True}}, "{namespace}", session_id="{namespace}")

listed = json.loads(beu.ledger_list_handler({{
    "namespace": "{namespace}",
    "thread_id": "{namespace}",
    "limit": 10
}}, session_key="{namespace}"))
searched = json.loads(beu.ledger_search_handler({{
    "namespace": "{namespace}",
    "query": "detailed explanations",
    "thread_id": "{namespace}",
    "kind": "user_turn",
    "limit": 5
}}, session_key="{namespace}"))
got = json.loads(beu.ledger_get_handler({{
    "namespace": "{namespace}",
    "entry_id": "{namespace}:llm:user"
}}, session_key="{namespace}"))

print(json.dumps({{
    "empty_before": empty_before,
    "listed": listed,
    "searched": searched,
    "got": got,
}}))
"#,
    );

    let output = harness.run_python(&script);
    assert!(
        output.status.success(),
        "contract test failed:\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    let stdout = String::from_utf8(output.stdout).expect("utf8 stdout");
    let payload: serde_json::Value = serde_json::from_str(stdout.trim()).expect("json output");
    assert_eq!(
        payload["empty_before"]["entries"],
        serde_json::json!([]),
        "namespace should start empty"
    );
    assert!(payload["listed"]["entries"].as_array().map(|hits| hits.len()).unwrap_or(0) >= 1);
    assert_eq!(payload["searched"]["entries"].as_array().map(|hits| hits.len()), Some(1));
    assert_eq!(payload["searched"]["entries"][0]["source_type"], "user_turn");
    assert_eq!(
        payload["searched"]["entries"][0]["content"],
        "User prefers detailed explanations"
    );
}
