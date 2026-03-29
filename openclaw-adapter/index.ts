import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import type { OpenClawConfig } from "../../openclaw/src/config/config.js";
import {
  type MemoryFlushPlan,
  registerMemoryFlushPlanResolver,
  registerMemoryPromptSection,
  registerMemoryRuntime,
  type MemoryPluginRuntime,
  type MemoryPromptSectionBuilder,
  type RegisteredMemorySearchManager,
  type MemoryProviderStatus,
  type MemoryEmbeddingProbeResult,
} from "../../openclaw/src/plugins/memory-state.js";
import { createBeuProcess, type BeuProcess } from "./beu-process.js";
import { buildBeuFlushPlan } from "./flush-plan.js";
import { buildBeuPromptSection } from "./prompt-section.js";

interface BeuSearchManager extends RegisteredMemorySearchManager {
  beu: BeuProcess;
  agentId: string;
}

const searchManagers: Map<string, BeuSearchManager> = new Map();

function resolveNamespace(params: { sessionKey?: string; sessionId?: string; agentId?: string }): string {
  return params.sessionKey || params.sessionId || params.agentId || "default";
}

function truncateText(value: string, max = 2000): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

async function indexTextEntry(params: {
  namespace: string;
  entryId: string;
  sourceType: string;
  sourceId: string;
  content: string;
  metadata: Record<string, unknown>;
}) {
  const text = params.content.trim();
  if (!text) {
    return;
  }
  const beu = createBeuProcess({ namespace: params.namespace });
  await beu.index(
    [
      {
        entry_id: params.entryId,
        source_type: params.sourceType,
        source_id: params.sourceId,
        content: truncateText(text),
        metadata: params.metadata,
      },
    ],
    { namespace: params.namespace, embed: false },
  );
}

function buildBeuRuntime(): MemoryPluginRuntime {
  return {
    async getMemorySearchManager(params: {
      cfg: OpenClawConfig;
      agentId: string;
      purpose?: "default" | "status";
    }): Promise<{ manager: RegisteredMemorySearchManager | null; error?: string }> {
      const key = `${params.agentId}`;
      let manager = searchManagers.get(key);

      if (!manager) {
        try {
          const beu = createBeuProcess();
          manager = {
            beu,
            agentId: params.agentId,
            status() {
              return {
                available: true,
                vectorAvailable: false,
                lastError: undefined,
              };
            },
            async probeEmbeddingAvailability(): Promise<MemoryEmbeddingProbeResult> {
              return { available: false, error: "BeU uses FTS5, no embeddings" };
            },
            async probeVectorAvailability(): Promise<boolean> {
              return false;
            },
            async sync(params) {
              // BeU handles indexing internally via the index command
              // or through recall during search
            },
            async close() {
              searchManagers.delete(key);
            },
          };
          searchManagers.set(key, manager);
        } catch (error) {
          return {
            manager: null,
            error: error instanceof Error ? error.message : "Failed to create BeU process",
          };
        }
      }

      return { manager };
    },

    resolveMemoryBackendConfig(params: {
      cfg: OpenClawConfig;
      agentId: string;
    }) {
      return {
        backend: "builtin" as const,
      };
    },

    async closeAllMemorySearchManagers() {
      for (const manager of searchManagers.values()) {
        await manager.close();
      }
      searchManagers.clear();
    },
  };
}

function buildBeuPromptSectionBuilder(): MemoryPromptSectionBuilder {
  return async (params) => {
    const beu = createBeuProcess();
    try {
      const identity = await beu.identity("all");
      const invariants = identity.invariants ?? [];
      const active = invariants.filter((inv: { status?: string }) => inv.status === "active");

      if (active.length === 0) {
        return [];
      }

      const lines = ["# User Preferences & Identity"];
      for (const inv of active.slice(0, 5)) {
        lines.push(`- ${inv.claim}`);
      }

      return [lines.join("\n")];
    } catch (error) {
      console.error("BeU prompt section build failed:", error);
      return [];
    }
  };
}

export default definePluginEntry({
  id: "beu-memory",
  name: "BeU Memory",
  description: "BetterClaw identity persistence and long-term memory using BeU binary",
  kind: "memory",
  configSchema: {
    type: "object",
    properties: {
      binaryPath: {
        type: "string",
        description: "Path to BeU binary (default: beu in PATH)",
      },
      namespace: {
        type: "string",
        description: "Agent namespace (default: agent ID)",
      },
    },
  },
  register(api) {
    api.registerMemoryPromptSection(buildBeuPromptSectionBuilder());
    api.registerMemoryFlushPlan(buildBeuFlushPlan());
    api.registerMemoryRuntime(buildBeuRuntime());

    api.registerHook("llm_input", async (event, ctx) => {
      await indexTextEntry({
        namespace: resolveNamespace(ctx),
        entryId: `${event.sessionId}:${event.runId || "llm_input"}:user`,
        sourceType: "ledger_entry",
        sourceId: event.runId || event.sessionId,
        content: typeof event.prompt === "string" ? event.prompt : "",
        metadata: {
          kind: "user_turn",
          session_id: event.sessionId,
          run_id: event.runId,
          provider: event.provider,
          model: event.model,
          images_count: event.imagesCount,
        },
      });
    });

    api.registerHook("llm_output", async (event, ctx) => {
      await indexTextEntry({
        namespace: resolveNamespace(ctx),
        entryId: `${event.sessionId}:${event.runId || "llm_output"}:assistant`,
        sourceType: "ledger_entry",
        sourceId: event.runId || event.sessionId,
        content: (event.assistantTexts || []).join("\n\n"),
        metadata: {
          kind: "agent_turn",
          session_id: event.sessionId,
          run_id: event.runId,
          provider: event.provider,
          model: event.model,
          usage: event.usage || {},
        },
      });
    });

    api.registerHook("after_tool_call", async (event, ctx) => {
      const rawResult = event.result ?? event.error ?? "";
      const content =
        typeof rawResult === "string" ? rawResult : JSON.stringify(rawResult, null, 2);
      await indexTextEntry({
        namespace: resolveNamespace(ctx),
        entryId: `${ctx.sessionId || ctx.runId || "tool"}:${event.toolCallId || event.toolName}:tool`,
        sourceType: "ledger_entry",
        sourceId: event.toolCallId || event.toolName,
        content,
        metadata: {
          kind: "tool_result",
          tool_name: event.toolName,
          tool_call_id: event.toolCallId,
          run_id: event.runId,
          duration_ms: event.durationMs,
          error: event.error,
        },
      });
    });

    api.registerTool(
      async (ctx) => {
        const { createBeuRecallTool } = await import("./tools/recall.js");
        return createBeuRecallTool({
          config: ctx.config,
          agentSessionKey: ctx.sessionKey,
        });
      },
      { names: ["beu_recall"] },
    );

    api.registerTool(
      async (ctx) => {
        const { createBeuDistillTool } = await import("./tools/distill.js");
        return createBeuDistillTool({
          config: ctx.config,
          agentSessionKey: ctx.sessionKey,
        });
      },
      { names: ["beu_distill"] },
    );
  },
});

export { buildBeuRuntime, buildBeuPromptSectionBuilder, buildBeuFlushPlan };
