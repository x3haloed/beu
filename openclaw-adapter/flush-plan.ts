import type { OpenClawConfig } from "../../openclaw/src/config/config.js";
import type { MemoryFlushPlan } from "../../openclaw/src/plugins/memory-state.js";

export function buildBeuFlushPlan(): (params: {
  cfg?: OpenClawConfig;
  nowMs?: number;
}) => MemoryFlushPlan | null {
  return () => {
    return {
      softThresholdTokens: 4000,
      forceFlushTranscriptBytes: 150000,
      reserveTokensFloor: 500,
      prompt:
        "Memory flush triggered. Use beu_distill to compress the conversation into memory artifacts.",
      systemPrompt:
        "# Memory Flush\n\nThe context is near capacity. When possible, call the beu_distill tool to compress the conversation into persistent memory before continuing.",
      relativePath: "memory/flush.md",
    };
  };
}
