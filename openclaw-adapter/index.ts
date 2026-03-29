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
