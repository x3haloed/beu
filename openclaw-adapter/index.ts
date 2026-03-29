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
  embeddingProvider?: EmbeddingProviderConfig;
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
        metadata: {
          ...params.metadata,
          thread_id: params.threadId,
        },
      },
    ],
    {
      namespace: params.namespace,
      embed: Boolean(params.embeddingProvider),
      embeddingProvider: params.embeddingProvider
        ? {
            provider: params.embeddingProvider.provider,
            model: params.embeddingProvider.model,
            base_url: params.embeddingProvider.base_url,
            api_key: params.embeddingProvider.api_key,
            headers: params.embeddingProvider.headers,
            output_dimensionality: params.embeddingProvider.output_dimensionality,
          }
        : undefined,
    },
  );
}

type EmbeddingCandidate = {
  pluginId: string;
  provider: RegisteredMemoryEmbeddingProvider;
};

type EmbeddingProviderConfig = {
  provider: string;
  model: string;
  base_url?: string;
  api_key?: string;
  headers?: Record<string, string>;
  output_dimensionality?: number;
  pluginId: string;
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

function resolveMemorySearchConfigForEmbeddingCandidates(params: {
  cfg: OpenClawConfig;
  agentId: string;
}) {
  const normalizedAgentId = params.agentId.trim().toLowerCase();
  const agentMemorySearch = params.cfg.agents?.list?.find(
    (entry) => entry?.id?.trim().toLowerCase() === normalizedAgentId,
  )?.memorySearch;
  if (agentMemorySearch && hasEmbeddingsConfigured(agentMemorySearch)) {
    return agentMemorySearch;
  }
  return params.cfg.agents?.defaults?.memorySearch;
}

function hasEmbeddingsConfigured(memorySearch?: {
  provider?: string;
  model?: string;
  remote?: { baseUrl?: string; apiKey?: string; headers?: Record<string, string> };
  local?: { modelPath?: string };
}) {
  if (!memorySearch) {
    return false;
  }
  if (memorySearch.provider && memorySearch.provider.trim() !== "auto") {
    return true;
  }
  if (memorySearch.remote?.baseUrl || memorySearch.remote?.apiKey) {
    return true;
  }
  if (memorySearch.local?.modelPath) {
    return true;
  }
  return false;
}

function findEmbeddingCandidates(params: {
  cfg: OpenClawConfig;
  agentId: string;
}): EmbeddingCandidate[] {
  const memorySearch = resolveMemorySearchConfigForEmbeddingCandidates(params);
  const pluginIds = listMemoryPluginIds(params);
  const providers = listRegisteredMemoryEmbeddingProviders();
  const configuredProviderId = memorySearch?.provider?.trim();
  const candidates: EmbeddingCandidate[] = [];
  if (configuredProviderId && configuredProviderId !== "auto") {
    for (const pluginId of pluginIds) {
      for (const provider of providers) {
        if (provider.ownerPluginId === pluginId && provider.adapter.id === configuredProviderId) {
          candidates.push({ pluginId, provider });
        }
      }
    }
    if (candidates.length > 0) {
      return candidates;
    }
  }
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

function resolveEmbeddingProviderConfig(params: {
  cfg: OpenClawConfig;
  agentId: string;
}): EmbeddingProviderConfig | undefined {
  const memorySearch = resolveMemorySearchConfig(params.cfg, params.agentId);
  const candidates = findEmbeddingCandidates(params);

  if (memorySearch?.provider && memorySearch.provider !== "auto") {
    const providerConfig: EmbeddingProviderConfig = {
      provider: memorySearch.provider,
      model: memorySearch.model || "",
      pluginId: "configured",
    };
    if (memorySearch.remote) {
      providerConfig.base_url = memorySearch.remote.baseUrl;
      providerConfig.api_key = memorySearch.remote.apiKey;
      providerConfig.headers = memorySearch.remote.headers;
    }
    if (memorySearch.local) {
      providerConfig.model = memorySearch.local.modelPath || providerConfig.model;
    }
    if (typeof memorySearch.outputDimensionality === "number") {
      providerConfig.output_dimensionality = memorySearch.outputDimensionality;
    }
    return providerConfig;
  }

  const selected = candidates[0];
  if (!selected) {
    return undefined;
  }
  const providerConfig: EmbeddingProviderConfig = {
    provider: selected.provider.adapter.id,
    model: memorySearch?.model || selected.provider.defaultModel || "",
    pluginId: selected.pluginId,
  };
  if (memorySearch?.remote) {
    providerConfig.base_url = memorySearch.remote.baseUrl;
    providerConfig.api_key = memorySearch.remote.apiKey;
    providerConfig.headers = memorySearch.remote.headers;
  }
  if (memorySearch?.local) {
    providerConfig.model = memorySearch.local.modelPath || providerConfig.model;
  }
  if (typeof memorySearch?.outputDimensionality === "number") {
    providerConfig.output_dimensionality = memorySearch.outputDimensionality;
  }
  return providerConfig;
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
      const cfg = ctx.config || ctx.runtimeConfig || ({} as OpenClawConfig);
      const agentId = ctx.agentId || event.sessionId || "default";
      const embeddingProvider = text.trim()
        ? resolveEmbeddingProviderConfig({
            cfg,
            agentId,
          })
        : undefined;
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
        embeddingProvider,
      });
    });

    api.registerHook("llm_output", async (event, ctx) => {
      const content = (event.assistantTexts || []).join("\n\n");
      const cfg = ctx.config || ctx.runtimeConfig || ({} as OpenClawConfig);
      const agentId = ctx.agentId || event.sessionId || "default";
      const embeddingProvider = content.trim()
        ? resolveEmbeddingProviderConfig({
            cfg,
            agentId,
          })
        : undefined;
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
          embedding_plugin_id: embeddingProvider?.pluginId,
          embedding_provider_id: embeddingProvider?.provider,
        },
        embeddingProvider,
      });
    });

    api.registerHook("after_tool_call", async (event, ctx) => {
      const rawResult = event.result ?? event.error ?? "";
      const content =
        typeof rawResult === "string" ? rawResult : JSON.stringify(rawResult, null, 2);
      const cfg = ctx.config || ctx.runtimeConfig || ({} as OpenClawConfig);
      const agentId = ctx.agentId || ctx.sessionId || "default";
      const embeddingProvider = content.trim()
        ? resolveEmbeddingProviderConfig({
            cfg,
            agentId,
          })
        : undefined;
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
          embedding_plugin_id: embeddingProvider?.pluginId,
          embedding_provider_id: embeddingProvider?.provider,
        },
        embeddingProvider,
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
