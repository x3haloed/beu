#[path = "hermes_adapter_support.rs"]
mod hermes_adapter_support;

use hermes_adapter_support::hermes_harness;

#[test]
fn hermes_plugin_loader_discovers_beu_adapter_without_hardcoded_paths() {
    let python = r#"
import json
import os
import sys
from pathlib import Path

repo_root = Path(os.environ["BEU_HERMES_AGENT_REPO"])
sys.path.insert(0, str(repo_root))

from hermes_cli.plugins import get_plugin_manager

mgr = get_plugin_manager()
mgr.discover_and_load()
plugins = mgr.list_plugins()
print(json.dumps({
    "plugins": plugins,
}, sort_keys=True))
    "#;

    let harness = hermes_harness();
    let output = harness.run_python(python);

    assert!(
        output.status.success(),
        "python failed:\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    let stdout = String::from_utf8(output.stdout).expect("utf8 stdout");
    let payload: serde_json::Value = serde_json::from_str(stdout.trim()).expect("json output");
    let plugins = payload["plugins"].as_array().expect("plugins array");
    let beu = plugins
        .iter()
        .find(|plugin| plugin["name"] == "beu")
        .expect("beu plugin missing");

    assert_eq!(beu["enabled"], true, "beu plugin should load successfully");
    assert_eq!(beu["tools"], 3, "beu should register exactly three tools");
    assert_eq!(beu["hooks"], 5, "beu should register exactly five hooks");
    assert!(beu["error"].is_null(), "beu plugin should not report an error");
}
