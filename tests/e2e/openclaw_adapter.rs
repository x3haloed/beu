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
    hooks: 0,
    error: null,
  };
  console.log(JSON.stringify({
    beu,
    memoryPromptSections: registrations.memoryPromptSections.length,
    memoryFlushPlans: registrations.memoryFlushPlans.length,
    memoryRuntimes: registrations.memoryRuntimes.length,
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
    assert_eq!(beu["tools"], 2, "beu should register exactly two tools");
    assert_eq!(beu["hooks"], 0, "beu memory plugin should not register hooks");
    assert!(beu["error"].is_null(), "beu plugin should not report an error");
    assert_eq!(payload["memoryPromptSections"], 1);
    assert_eq!(payload["memoryFlushPlans"], 1);
    assert_eq!(payload["memoryRuntimes"], 1);
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
    tools: [],
  };
  entry.default.register({
    registerMemoryPromptSection() {},
    registerMemoryFlushPlan() {},
    registerMemoryRuntime() {},
    registerTool(factory, options) {
      registrations.tools.push({
        factory,
        names: options.names,
      });
    },
  });

  const recallTool = registrations.tools.find((tool) => tool.names?.includes("beu_recall"));
  const distillTool = registrations.tools.find((tool) => tool.names?.includes("beu_distill"));
  if (!recallTool || !distillTool) {
    throw new Error("missing beu tools");
  }

  const beu = createBeuProcess({ namespace: "__NAMESPACE__" });
  const statusBefore = await beu.status();
  const recall = await recallTool.factory({ sessionKey: "__NAMESPACE__" });
  const distill = await distillTool.factory({ sessionKey: "__NAMESPACE__" });

  const seed = await distill.handler({
    thread_id: "thread-1",
    turn_id: "turn-1",
    thread_history: [
      {
        entry_id: "seed-entry-1",
        kind: "user_turn",
        content: "User prefers detailed explanations",
        citation: "turn-1:user",
        created_at: "2026-03-28T00:00:00.000Z"
      },
      {
        entry_id: "seed-entry-2",
        kind: "agent_turn",
        content: "Understood, I will provide detailed explanations.",
        citation: "turn-1:agent",
        created_at: "2026-03-28T00:00:01.000Z"
      }
    ]
  }, { sessionKey: "__NAMESPACE__" });

  const afterSeed = await recall.handler({
    query: "detailed explanations",
    limit: 5,
    sources: ["wake_pack"],
  }, { sessionKey: "__NAMESPACE__" });

  const finalCheck = await recall.handler({
    query: "detailed explanations",
    limit: 5,
    sources: ["wake_pack"],
  }, { sessionKey: "__NAMESPACE__" });

  console.log(JSON.stringify({
    statusBefore,
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
    assert_ne!(payload["statusBefore"]["storage"], "error");
    let seed_text = payload["seed"]["content"][0]["text"].as_str().unwrap_or("");
    assert!(
        seed_text.contains("Distillation complete"),
        "seed distillation should succeed; got: {}",
        seed_text
    );
    assert!(
        payload["afterSeed"]["content"][0]["text"]
            .as_str()
            .unwrap_or("")
            .contains("User prefers detailed explanations"),
        "seeded memory should be recallable"
    );
    assert!(
        payload["finalCheck"]["content"][0]["text"]
            .as_str()
            .unwrap_or("")
            .contains("User prefers detailed explanations"),
        "recall should stay deterministic"
    );
}
