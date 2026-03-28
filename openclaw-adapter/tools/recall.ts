import type { OpenClawPluginToolContext } from "../../openclaw/src/plugins/types.js";
import type { OpenClawConfig } from "../../openclaw/src/config/config.js";
import { createBeuProcess, type BeuProcess } from "../beu-process.js";

interface BeuRecallToolOptions {
  config: OpenClawConfig;
  agentSessionKey: string;
}

export function createBeuRecallTool(options: BeuRecallToolOptions) {
  return {
    name: "beu_recall",
    description:
      "Search long-term memory for relevant context, facts, and user preferences. Use this proactively when the user references past conversations or you need to recall specific information about the user or project.",
    inputSchema: {
      type: "object" as const,
      properties: {
        query: {
          type: "string",
          description: "Search query describing what to recall",
        },
        limit: {
          type: "number",
          description: "Maximum number of results (default: 5)",
          default: 5,
        },
        sources: {
          type: "array",
          items: { type: "string" },
          description: "Sources to search: invariant, fact, wake_pack",
          default: ["invariant", "fact", "wake_pack"],
        },
      },
      required: ["query"],
    },
    handler: async (params: { query: string; limit?: number; sources?: string[] }, ctx: OpenClawPluginToolContext) => {
      const beu = createBeuProcess({
        namespace: ctx.sessionKey,
      });

      try {
        const hits = await beu.recall({
          query: params.query,
          limit: params.limit || 5,
          sources: params.sources,
        });

        if (hits.length === 0) {
          return {
            content: [
              {
                type: "text" as const,
                text: "No relevant memories found for query.",
              },
            ],
          };
        }

        const text = hits
          .map((hit, i) => {
            return `[${i + 1}] ${hit.source_type}: ${hit.content.slice(0, 500)}`;
          })
          .join("\n\n");

        return {
          content: [
            {
              type: "text" as const,
              text,
            },
          ],
        };
      } catch (error) {
        return {
          content: [
            {
              type: "text" as const,
              text: `Memory recall failed: ${error instanceof Error ? error.message : "Unknown error"}`,
            },
          ],
        };
      }
    },
  };
}
