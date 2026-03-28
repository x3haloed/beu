import type { OpenClawConfig } from "../../openclaw/src/config/config.js";
import type { MemoryCitationsMode } from "../../openclaw/src/config/types.memory.js";
import { createBeuProcess } from "./beu-process.js";

export async function buildBeuPromptSection(params: {
  availableTools: Set<string>;
  citationsMode?: MemoryCitationsMode;
}): Promise<string[]> {
  try {
    const beu = createBeuProcess();
    const identity = await beu.identity("all");
    const invariants = identity.invariants ?? [];
    const active = invariants.filter((inv) => inv.status === "active");

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
}
