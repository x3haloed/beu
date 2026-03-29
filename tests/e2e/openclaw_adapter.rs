#[path = "openclaw_adapter_support.rs"]
mod openclaw_adapter_support;

use openclaw_adapter_support::openclaw_harness;

#[test]
fn openclaw_plugin_loader_discovers_beu_adapter_without_hardcoded_paths() {
    let script = r#"
import path from "node:path";
import { pathToFileURL } from "node:url";

void (async () => {
  const beuAdapterDir = path.resolve(process.cwd(), "..", "beu", "openclaw-adapter");
  const entry = await import(pathToFileURL(path.join(beuAdapterDir, "index.ts")).href);
  const registrations = {
    memoryPromptSections: [],
    memoryFlushPlans: [],
    memoryRuntimes: [],
    hooks: [],
    tools: [],
  };
  entry.default.register({
    registerMemoryPromptSection(builder) {
      registrations.memoryPromptSections.push(builder);
    },
    registerMemoryFlushPlan(resolver) {
      registrations.memoryFlushPlans.push(resolver);
    },
    registerMemoryRuntime(runtime) {
      registrations.memoryRuntimes.push(runtime);
    },
    registerHook(events, handler, options) {
      registrations.hooks.push({ events, handler, options });
    },
    registerTool(factory, options) {
      registrations.tools.push({
        factory,
        names: options.names,
      });
    },
  });

  const beu = {
    id: "beu-memory",
    enabled: true,
    status: "loaded",
    tools: registrations.tools.length,
    hooks: registrations.hooks.length,
    error: null,
  };
  console.log(JSON.stringify({
    beu,
    memoryPromptSections: registrations.memoryPromptSections.length,
    memoryFlushPlans: registrations.memoryFlushPlans.length,
    memoryRuntimes: registrations.memoryRuntimes.length,
    hooks: registrations.hooks.length,
    tools: registrations.tools.map((tool) => tool.names),
  }, null, 2));
  process.exit(0);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"#;

    let harness = openclaw_harness();
    let output = harness.run_tsx(script);

    assert!(
        output.status.success(),
        "tsx failed:\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    let stdout = String::from_utf8(output.stdout).expect("utf8 stdout");
    let payload: serde_json::Value = serde_json::from_str(stdout.trim()).expect("json output");
    let beu = payload["beu"].as_object().expect("beu plugin missing");

    assert_eq!(beu["enabled"], true, "beu plugin should load successfully");
    assert_eq!(beu["tools"], 3, "beu should register exactly three tools");
    assert_eq!(beu["hooks"], 3, "beu memory plugin should register passive indexing hooks");
    assert!(beu["error"].is_null(), "beu plugin should not report an error");
    assert_eq!(payload["memoryPromptSections"], 1);
    assert_eq!(payload["memoryFlushPlans"], 1);
    assert_eq!(payload["memoryRuntimes"], 1);
    assert_eq!(payload["hooks"], 3);
}

#[test]
fn openclaw_adapter_contract_is_clean_and_idempotent() {
    let harness = openclaw_harness();
    let namespace = format!("contract-{}", uuid::Uuid::new_v4());

    let script = r#"
import path from "node:path";
import { pathToFileURL } from "node:url";

void (async () => {
  const beuAdapterDir = path.resolve(process.cwd(), "..", "beu", "openclaw-adapter");
  const entry = await import(pathToFileURL(path.join(beuAdapterDir, "index.ts")).href);
  const { createBeuProcess } = await import(pathToFileURL(path.join(beuAdapterDir, "beu-process.ts")).href);
  const registrations = {
    hooks: [],
    tools: [],
  };
  entry.default.register({
    registerMemoryPromptSection() {},
    registerMemoryFlushPlan() {},
    registerMemoryRuntime() {},
    registerHook(events, handler, options) {
      registrations.hooks.push({ events, handler, options });
    },
    registerTool(factory, options) {
      registrations.tools.push({
        factory,
        names: options.names,
      });
    },
  });

  const listTool = registrations.tools.find((tool) => tool.names?.includes("ledger_list"));
  const searchTool = registrations.tools.find((tool) => tool.names?.includes("ledger_search"));
  const getTool = registrations.tools.find((tool) => tool.names?.includes("ledger_get"));
  if (!listTool || !searchTool || !getTool) {
    throw new Error("missing ledger tools");
  }

  const beu = createBeuProcess({ namespace: "__NAMESPACE__" });
  const list = await listTool.factory({ sessionKey: "__NAMESPACE__" });
  const search = await searchTool.factory({ sessionKey: "__NAMESPACE__" });
  const get = await getTool.factory({ sessionKey: "__NAMESPACE__" });

  const emptyBefore = (await beu.ledgerList({
    thread_id: "__NAMESPACE__",
    limit: 5,
  })).data;

  const seed = (await beu.index([
    {
      entry_id: "seed-entry-1",
      source_type: "ledger_entry",
      source_id: "turn-1",
      content: "User prefers detailed explanations",
      metadata: {
        kind: "user_turn",
        thread_id: "__NAMESPACE__",
        turn_id: "turn-1",
        citation: "turn-1:user",
      },
    },
  ], { namespace: "__NAMESPACE__", embed: false })).data;

  const afterSeed = (await beu.ledgerSearch({
    query: "detailed explanations",
    limit: 5,
    thread_id: "__NAMESPACE__",
    kind: "user_turn",
  })).data;

  const finalCheck = (await beu.ledgerGet("seed-entry-1")).data;

  console.log(JSON.stringify({
    emptyBefore,
    seed,
    afterSeed,
    finalCheck,
  }, null, 2));
  process.exit(0);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"#.replace("__NAMESPACE__", &namespace);

    let output = harness.run_tsx(&script);
    assert!(
        output.status.success(),
        "contract test failed:\nstdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    let stdout = String::from_utf8(output.stdout).expect("utf8 stdout");
    let payload: serde_json::Value = serde_json::from_str(stdout.trim()).expect("json output");
    assert_eq!(payload["emptyBefore"]["entries"].as_array().map(|v| v.len()), Some(0));
    assert!(payload["seed"]["indexed"].as_i64().unwrap_or(0) >= 1);
    assert_eq!(payload["afterSeed"]["entries"].as_array().map(|v| v.len()), Some(1));
    assert_eq!(payload["afterSeed"]["entries"][0]["kind"], "user_turn");
    assert_eq!(
        payload["afterSeed"]["entries"][0]["content"],
        "User prefers detailed explanations"
    );
    assert_eq!(payload["finalCheck"]["content"], "User prefers detailed explanations");
}
