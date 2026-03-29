import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import type { OpenClawConfig } from "../../openclaw/src/config/config.js";
import {
  type MemoryFlushPlan,
  type MemoryEmbeddingProbeResult,
  registerMemoryFlushPlanResolver,
  registerMemoryPromptSection,
  registerMemoryRuntime,
  type MemoryPluginRuntime,
  type MemoryPromptSectionBuilder,
  type RegisteredMemorySearchManager,
  type MemoryProviderStatus,
} from "../../openclaw/src/plugins/memory-state.js";
import { getActivePluginRegistry } from "../../openclaw/src/plugins/runtime.js";
import {
  listRegisteredMemoryEmbeddingProviders,
  type RegisteredMemoryEmbeddingProvider,
} from "../../openclaw/src/plugins/memory-embedding-providers.js";
import { resolveMemorySearchConfig } from "../../openclaw/packages/memory-host-sdk/src/runtime-core.js";
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
  threadId: string;
  entryId: string;
  sourceType: string;
  sourceId: string;
  content: string;
  metadata: Record<string, unknown>;
  embedding?: number[];
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
        embedding: params.embedding,
        metadata: {
          ...params.metadata,
          thread_id: params.threadId,
        },
      },
    ],
    { namespace: params.namespace, embed: false },
  );
}

type EmbeddingCandidate = {
  pluginId: string;
  provider: RegisteredMemoryEmbeddingProvider;
};

function resolvePreferredMemoryPluginId(cfg: OpenClawConfig): string | undefined {
  const slot = cfg.plugins?.slots?.memory?.trim();
  if (!slot || slot === "none") {
    return undefined;
  }
  return slot;
}

function listMemoryPluginIds(params: { cfg: OpenClawConfig; agentId: string }): string[] {
  const registry = getActivePluginRegistry();
  const ordered = new Set<string>();
  const add = (value?: string | null) => {
    const trimmed = value?.trim();
    if (trimmed) {
      ordered.add(trimmed);
    }
  };
  add(resolvePreferredMemoryPluginId(params.cfg));
  for (const record of registry?.plugins ?? []) {
    if (record.kind === "memory" && record.status === "loaded") {
      add(record.id);
    }
  }
  return Array.from(ordered);
}

function findEmbeddingCandidates(params: {
  cfg: OpenClawConfig;
  agentId: string;
}): EmbeddingCandidate[] {
  const pluginIds = listMemoryPluginIds(params);
  const providers = listRegisteredMemoryEmbeddingProviders();
  const candidates: EmbeddingCandidate[] = [];
  for (const pluginId of pluginIds) {
    for (const provider of providers) {
      if (provider.ownerPluginId === pluginId) {
        candidates.push({ pluginId, provider });
      }
    }
  }
  if (candidates.length > 0) {
    return candidates;
  }
  return providers.map((provider) => ({
    pluginId: provider.ownerPluginId ?? "unknown",
    provider,
  }));
}

async function embedWithBestAvailableProvider(params: {
  cfg: OpenClawConfig;
  agentId: string;
  text: string;
}): Promise<{ embedding?: number[]; providerId?: string; pluginId?: string }> {
  const memorySearch = resolveMemorySearchConfig(params.cfg, params.agentId);
  const candidates = findEmbeddingCandidates(params);

  for (const candidate of candidates) {
    try {
      const created = await candidate.provider.adapter.create({
        config: params.cfg,
        model: memorySearch?.model || "",
        remote: memorySearch?.remote
          ? {
              baseUrl: memorySearch.remote.baseUrl,
              apiKey: memorySearch.remote.apiKey,
              headers: memorySearch.remote.headers,
            }
          : undefined,
        local: memorySearch?.local
          ? {
              modelPath: memorySearch.local.modelPath,
              modelCacheDir: memorySearch.local.modelCacheDir,
            }
          : undefined,
        outputDimensionality: memorySearch?.outputDimensionality,
      });
      if (!created.provider) {
        continue;
      }
      return {
        embedding: await created.provider.embedQuery(params.text),
        providerId: candidate.provider.adapter.id,
        pluginId: candidate.pluginId,
      };
    } catch (error) {
      console.error("BeU embedding candidate failed", {
        agentId: params.agentId,
        pluginId: candidate.pluginId,
        providerId: candidate.provider.adapter.id,
        error,
      });
    }
  }

  return {};
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
      const text = typeof event.prompt === "string" ? event.prompt : "";
      const embedding = text.trim()
        ? await embedWithBestAvailableProvider({
            cfg: ctx.config || ctx.runtimeConfig || ({} as OpenClawConfig),
            agentId: ctx.agentId || event.sessionId || "default",
            text,
          })
        : {};
      await indexTextEntry({
        namespace: resolveNamespace(ctx),
        threadId: String(event.sessionId || event.runId || ctx.sessionKey || "default"),
        entryId: `${event.sessionId}:${event.runId || "llm_input"}:user`,
        sourceType: "user_turn",
        sourceId: event.runId || event.sessionId,
        content: text,
        metadata: {
          session_id: event.sessionId,
          run_id: event.runId,
          provider: event.provider,
          model: event.model,
          images_count: event.imagesCount,
        },
        embedding: embedding.embedding,
      });
    });

    api.registerHook("llm_output", async (event, ctx) => {
      const content = (event.assistantTexts || []).join("\n\n");
      const embedding = content.trim()
        ? await embedWithBestAvailableProvider({
            cfg: ctx.config || ctx.runtimeConfig || ({} as OpenClawConfig),
            agentId: ctx.agentId || event.sessionId || "default",
            text: content,
          })
        : {};
      await indexTextEntry({
        namespace: resolveNamespace(ctx),
        threadId: String(event.sessionId || event.runId || ctx.sessionKey || "default"),
        entryId: `${event.sessionId}:${event.runId || "llm_output"}:assistant`,
        sourceType: "assistant_turn",
        sourceId: event.runId || event.sessionId,
        content,
        metadata: {
          session_id: event.sessionId,
          run_id: event.runId,
          provider: event.provider,
          model: event.model,
          usage: event.usage || {},
          embedding_provider_id: embedding.providerId,
          embedding_plugin_id: embedding.pluginId,
        },
        embedding: embedding.embedding,
      });
    });

    api.registerHook("after_tool_call", async (event, ctx) => {
      const rawResult = event.result ?? event.error ?? "";
      const content =
        typeof rawResult === "string" ? rawResult : JSON.stringify(rawResult, null, 2);
      const embedding = content.trim()
        ? await embedWithBestAvailableProvider({
            cfg: ctx.config || ctx.runtimeConfig || ({} as OpenClawConfig),
            agentId: ctx.agentId || ctx.sessionId || "default",
            text: content,
          })
        : {};
      await indexTextEntry({
        namespace: resolveNamespace(ctx),
        threadId: String(ctx.sessionId || ctx.runId || ctx.sessionKey || "default"),
        entryId: `${ctx.sessionId || ctx.runId || "tool"}:${event.toolCallId || event.toolName}:tool`,
        sourceType: "tool_result",
        sourceId: event.toolCallId || event.toolName,
        content,
        metadata: {
          tool_name: event.toolName,
          tool_call_id: event.toolCallId,
          run_id: event.runId,
          duration_ms: event.durationMs,
          error: event.error,
          embedding_provider_id: embedding.providerId,
          embedding_plugin_id: embedding.pluginId,
        },
        embedding: embedding.embedding,
      });
    });

    api.registerTool(
      async (ctx) => {
        const beu = createBeuProcess({ namespace: ctx.sessionKey });
        return {
          name: "ledger_list",
          description:
            "Browse recent ledger entries from runtime history with provenance-aware metadata. Use this to list or skim entries, not to search by content.",
          inputSchema: {
            type: "object" as const,
            properties: {
              thread_id: { type: "string" },
              limit: { type: "number", minimum: 1, default: 20 },
            },
          },
          handler: async (params: { thread_id?: string; limit?: number }, ctx) => {
            const result = await beu.ledgerList({
              thread_id: params.thread_id,
              limit: params.limit,
            });
            return {
              content: [{ type: "text" as const, text: JSON.stringify(result.data ?? {}, null, 2) }],
            };
          },
        };
      },
      { names: ["ledger_list"] },
    );

    api.registerTool(
      async (ctx) => {
        const beu = createBeuProcess({ namespace: ctx.sessionKey });
        return {
          name: "ledger_search",
          description:
            "Search ledger entries by meaning and keywords across runtime history, then return matching ledger entries with provenance-aware metadata.",
          inputSchema: {
            type: "object" as const,
            properties: {
              query: { type: "string" },
              thread_id: { type: "string" },
              limit: { type: "number", minimum: 1, default: 8 },
            },
            required: ["query"],
          },
          handler: async (params: { query: string; thread_id?: string; limit?: number }, ctx) => {
            const result = await beu.ledgerSearch({
              query: params.query,
              thread_id: params.thread_id,
              limit: params.limit,
            });
            return {
              content: [{ type: "text" as const, text: JSON.stringify(result.data ?? {}, null, 2) }],
            };
          },
        };
      },
      { names: ["ledger_search"] },
    );

    api.registerTool(
      async (ctx) => {
        const beu = createBeuProcess({ namespace: ctx.sessionKey });
        return {
          name: "ledger_get",
          description:
            "Fetch one ledger entry with full content, provenance, and citation metadata.",
          inputSchema: {
            type: "object" as const,
            properties: {
              entry_id: { type: "string" },
            },
            required: ["entry_id"],
          },
          handler: async (params: { entry_id: string }, ctx) => {
            const result = await beu.ledgerGet(params.entry_id);
            return {
              content: [{ type: "text" as const, text: JSON.stringify(result.data ?? {}, null, 2) }],
            };
          },
        };
      },
      { names: ["ledger_get"] },
    );
  },
});

export { buildBeuRuntime, buildBeuPromptSectionBuilder, buildBeuFlushPlan };
