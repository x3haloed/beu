import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { JsonlLedgerStore } from "./store.js";

const store = new JsonlLedgerStore();

export default definePluginEntry({
  id: "durable-ledger-memory",
  name: "Durable Ledger",
  description: "Hook-driven durable ledger storage using append-only JSONL files",
  kind: "memory",
  configSchema: {
    type: "object",
    properties: {
      storageRoot: {
        type: "string",
        description: "Root directory for append-only JSONL ledger files",
      },
      namespace: {
        type: "string",
        description: "Optional namespace override for ledger writes",
      },
    },
  },
  register(api) {
    api.registerHook("llm_input", async (event, ctx) => {
      await store.onLlmInput(event as Record<string, unknown>, ctx as Record<string, unknown>);
    });

    api.registerHook("llm_output", async (event, ctx) => {
      await store.onLlmOutput(event as Record<string, unknown>, ctx as Record<string, unknown>);
    });

    api.registerHook("after_tool_call", async (event, ctx) => {
      await store.onAfterToolCall(event as Record<string, unknown>, ctx as Record<string, unknown>);
    });
  },
});