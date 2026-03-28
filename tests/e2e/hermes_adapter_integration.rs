use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

struct HermesHarness {
    hermes_repo: PathBuf,
    hermes_home: PathBuf,
    venv_python: PathBuf,
    beu_binary: PathBuf,
    _temp_dir: tempfile::TempDir,
}

impl HermesHarness {
    fn new() -> Self {
        let hermes_repo = hermes_agent_repo_root().expect(
            "set BEU_HERMES_AGENT_REPO or keep a hermes-agent checkout adjacent to the beu repo",
        );
        let temp_dir = tempfile::tempdir().expect("tempdir");
        let hermes_home = temp_dir.path().join("hermes_home");
        let venv_dir = temp_dir.path().join("venv");
        let plugin_root = hermes_home.join("plugins").join("beu");
        fs::create_dir_all(&plugin_root).expect("plugin dir");

        let adapter_dir = hermes_adapter_dir();
        fs::copy(adapter_dir.join("plugin.yaml"), plugin_root.join("plugin.yaml"))
            .expect("copy plugin.yaml");
        fs::copy(adapter_dir.join("__init__.py"), plugin_root.join("__init__.py"))
            .expect("copy __init__.py");

        let venv_status = Command::new("python3")
            .arg("-m")
            .arg("venv")
            .arg(&venv_dir)
            .status()
            .expect("create venv");
        assert!(venv_status.success(), "failed to create isolated venv");

        let cargo_status = Command::new("cargo")
            .arg("build")
            .arg("--bin")
            .arg("beu")
            .current_dir(env!("CARGO_MANIFEST_DIR"))
            .status()
            .expect("build beu binary");
        assert!(cargo_status.success(), "failed to build beu binary");

        let venv_python = venv_dir.join("bin").join("python");
        let pip_status = Command::new(&venv_python)
            .arg("-m")
            .arg("pip")
            .arg("install")
            .arg("-e")
            .arg(".[all]")
            .current_dir(&hermes_repo)
            .status()
            .expect("install isolated deps");
        assert!(pip_status.success(), "failed to install isolated deps");

        let beu_binary = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("target/debug/beu");

        Self {
            hermes_repo,
            hermes_home,
            venv_python,
            beu_binary,
            _temp_dir: temp_dir,
        }
    }

    fn run_python(&self, script: &str) -> std::process::Output {
        Command::new(&self.venv_python)
            .current_dir(&self.hermes_repo)
            .env("BEU_HERMES_AGENT_REPO", &self.hermes_repo)
            .env("HERMES_HOME", &self.hermes_home)
            .env("BEU_BINARY_PATH", &self.beu_binary)
            .env("HERMES_ENABLE_PROJECT_PLUGINS", "0")
            .arg("-c")
            .arg(script)
            .output()
            .expect("run python")
    }
}

fn hermes_agent_repo_root() -> Option<PathBuf> {
    if let Ok(path) = env::var("BEU_HERMES_AGENT_REPO") {
        let candidate = PathBuf::from(path);
        if is_hermes_agent_repo(&candidate) {
            return Some(candidate);
        }
    }

    let cwd = env::current_dir().ok()?;
    let mut search_roots = Vec::new();
    for root in cwd.ancestors() {
        search_roots.push(root.to_path_buf());
        search_roots.push(root.join("hermes-agent"));
    }

    for candidate in search_roots {
        if is_hermes_agent_repo(&candidate) {
            return Some(candidate);
        }
    }

    None
}

fn is_hermes_agent_repo(path: &Path) -> bool {
    path.join("hermes_cli").join("plugins.py").exists()
        && path.join("tests").join("conftest.py").exists()
        && path.join("pyproject.toml").exists()
}

fn hermes_adapter_dir() -> PathBuf {
    env::current_dir()
        .expect("current dir")
        .join("hermes-adapter")
}

#[test]
fn hermes_plugin_loader_discovers_beu_adapter_without_hardcoded_paths() {
    let python = r#"
import json
import os
import sys
from pathlib import Path

repo_root = Path(os.environ["BEU_HERMES_AGENT_REPO"])
home = Path(os.environ["HERMES_HOME"])
sys.path.insert(0, str(repo_root))

from hermes_cli.plugins import get_plugin_manager

mgr = get_plugin_manager()
mgr.discover_and_load()
plugins = mgr.list_plugins()
print(json.dumps({
    "plugins": plugins,
}, sort_keys=True))
    "#;

    let harness = HermesHarness::new();
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
    assert_eq!(beu["tools"], 2, "beu should register exactly two tools");
    assert_eq!(beu["hooks"], 4, "beu should register exactly four hooks");
}

#[test]
fn hermes_adapter_contract_is_clean_and_idempotent() {
    let harness = HermesHarness::new();
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

cleanup = json.loads(beu.beu_recall_handler({{
    "query": "detailed explanations",
    "namespace": "{namespace}",
    "limit": 5,
    "sources": ["invariant"]
}}))
print(json.dumps({{
    "empty_before": empty_before,
    "seed": seed_result,
    "after_seed": after_seed,
    "cleanup": cleanup,
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
}
