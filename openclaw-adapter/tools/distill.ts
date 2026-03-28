import type { OpenClawPluginToolContext } from "../src/plugins/types.js";
import type { OpenClawConfig } from "../src/config/config.js";
import { createBeuProcess } from "../beu-process.js";

interface BeuDistillToolOptions {
  config: OpenClawConfig;
  agentSessionKey: string;
}

export function createBeuDistillTool(options: BeuDistillToolOptions) {
  return {
    name: "beu_distill",
    description:
      "Compress the current conversation into memory artifacts. Extracts facts, invariants, and creates a summary (wake_pack). Typically called automatically on context flush.",
    inputSchema: {
      type: "object" as const,
      properties: {
        thread_id: {
          type: "string",
          description: "Unique thread/conversation identifier",
        },
        turn_id: {
          type: "string",
          description: "Current turn identifier",
        },
        thread_history: {
          type: "array",
          description: "Array of turn events to compress",
          items: {
            type: "object",
            properties: {
              entry_id: { type: "string" },
              kind: { type: "string" },
              content: { type: "string" },
              citation: { type: "string" },
              created_at: { type: "string" },
            },
          },
        },
      },
      required: ["thread_id", "turn_id"],
    },
    handler: async (
      params: {
        thread_id: string;
        turn_id: string;
        thread_history: Array<{
          entry_id: string;
          kind: string;
          content: string;
          citation: string;
          created_at: string;
        }>;
      },
      ctx: OpenClawPluginToolContext,
    ) => {
      const beu = createBeuProcess({
        namespace: ctx.sessionKey,
      });

      try {
        const result = await beu.distill(
          params.thread_id,
          params.turn_id,
          params.thread_history || [],
        );

        return {
          content: [
            {
              type: "text" as const,
              text: `Distillation complete:\n\nWake Pack: ${result.wake_pack.summary}\n\nFacts extracted: ${result.facts.length}\nInvariants added: ${result.invariant_adds.length}`,
            },
          ],
        };
      } catch (error) {
        return {
          content: [
            {
              type: "text" as const,
              text: `Distillation failed: ${error instanceof Error ? error.message : "Unknown error"}`,
            },
          ],
        };
      }
    },
  };
}
