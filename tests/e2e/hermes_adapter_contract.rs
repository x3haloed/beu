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
proc = beu.get_beu()

empty_before = json.loads(beu.beu_recall_handler({{
    "query": "detailed explanations",
    "namespace": "{namespace}",
    "limit": 5,
    "sources": ["invariant"]
}}))
if not empty_before.get("success") or empty_before.get("hits") != []:
    raise SystemExit(json.dumps(empty_before))

status_before = beu.get_beu().status(namespace="{namespace}")
if status_before.get("storage") == "error":
    raise SystemExit("status check failed before seed")

seed_result = proc.call("index", {{
    "entries": [{{
        "entry_id": "seed-entry-1",
        "source_type": "ledger_entry",
        "source_id": "turn-1",
        "content": "User prefers detailed explanations",
        "metadata": {{"kind": "invariant"}}
    }}]
}}, namespace="{namespace}")
if not seed_result.get("ok"):
    raise SystemExit(json.dumps(seed_result))

after_seed = json.loads(beu.beu_recall_handler({{
    "query": "detailed explanations",
    "namespace": "{namespace}",
    "limit": 5,
    "sources": ["invariant"]
}}))
if not after_seed.get("success") or len(after_seed.get("hits", [])) != 1:
    raise SystemExit(json.dumps(after_seed))

final_check = json.loads(beu.beu_recall_handler({{
    "query": "detailed explanations",
    "namespace": "{namespace}",
    "limit": 5,
    "sources": ["invariant"]
}}))
print(json.dumps({{
    "empty_before": empty_before,
    "seed": seed_result,
    "after_seed": after_seed,
    "final_check": final_check,
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
        payload["empty_before"]["hits"],
        serde_json::json!([]),
        "namespace should start empty"
    );
    assert_eq!(payload["after_seed"]["hits"].as_array().map(|hits| hits.len()), Some(1));
    assert!(payload["seed"]["ok"].as_bool().unwrap_or(false));
    assert_eq!(payload["after_seed"]["hits"][0]["type"], "invariant");
    assert_eq!(
        payload["after_seed"]["hits"][0]["content"],
        "User prefers detailed explanations"
    );
    assert_eq!(payload["final_check"]["hits"].as_array().map(|hits| hits.len()), Some(1));
    assert_eq!(
        payload["final_check"]["hits"][0]["content"],
        "User prefers detailed explanations"
    );
}
