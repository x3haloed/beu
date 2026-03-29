import { spawn } from "child_process";
import * as jsonrpc from "jsonrpc-lite";

const DEFAULT_BINARY = "beu";

export interface BeuOptions {
  binaryPath?: string;
  namespace?: string;
}

export interface BeuRecallOptions {
  query: string;
  limit?: number;
  sources?: string[];
}

export interface BeuIndexEntry {
  entry_id: string;
  source_type: string;
  source_id: string;
  content: string;
  metadata?: Record<string, unknown>;
}

export interface BeuRecallHit {
  source_type: string;
  source_id: string;
  content: string;
  score: number;
  citation?: string;
}

export interface BeuIdentityResult {
  invariants: Array<{
    id: string;
    claim: string;
    status: string;
  }>;
  drift?: {
    flags: unknown[];
    contradictions: unknown[];
    merges: unknown[];
  };
  summary?: {
    wake_pack: string;
  };
}

export interface BeuStatusResult {
  storage: string;
  embedding_available?: boolean;
  vector_available?: boolean;
  last_distilled?: string;
  counts?: {
    invariants: number;
    facts: number;
    wake_packs: number;
    drift_items: number;
  };
}

export class BeuProcess {
  private binaryPath: string;
  private namespace: string;

  constructor(options: BeuOptions = {}) {
    this.binaryPath = options.binaryPath || process.env.BEU_BINARY_PATH || DEFAULT_BINARY;
    this.namespace = options.namespace || "default";
  }

  private async call(command: string, payload: Record<string, unknown>): Promise<any> {
    return new Promise((resolve, reject) => {
      const request = {
        version: "1.0.0",
        id: `${command}-${Date.now()}`,
        command,
        namespace: this.namespace,
        payload,
      };

      const proc = spawn(this.binaryPath, [], {
        stdio: ["pipe", "pipe", "pipe"],
      });

      let stdout = "";
      let stderr = "";

      proc.stdout.on("data", (data) => {
        stdout += data.toString();
      });

      proc.stderr.on("data", (data) => {
        stderr += data.toString();
      });

      proc.on("close", (code) => {
        if (code !== 0 && stderr) {
          reject(new Error(`BeU process error: ${stderr}`));
          return;
        }

        try {
          resolve(JSON.parse(stdout.trim()));
        } catch (error) {
          reject(new Error(`Invalid JSON response: ${stdout}`));
        }
      });

      proc.on("error", (error) => {
        reject(error);
      });

      proc.stdin.write(JSON.stringify(request) + "\n");
      proc.stdin.end();
    });
  }

  async recall(options: BeuRecallOptions): Promise<BeuRecallHit[]> {
    const payload = {
      query: options.query,
      limit: options.limit || 5,
      sources: options.sources || ["invariant", "fact", "wake_pack"],
    };

    const result = await this.call("recall", payload);

    if (!result.ok) {
      throw new Error(result.error || "Recall failed");
    }

    return result.data?.hits || [];
  }

  async identity(query: string = "all"): Promise<BeuIdentityResult> {
    const payload = { query, limit: 10 };

    const result = await this.call("identity", payload);

    if (!result.ok) {
      throw new Error(result.error || "Identity query failed");
    }

    return result.data || { invariants: [] };
  }

  async status(): Promise<BeuStatusResult> {
    const payload = {};

    const result = await this.call("status", payload);

    if (!result.ok) {
      throw new Error(result.error || "Status check failed");
    }

    return result.data || { storage: "unknown" };
  }

  async index(
    entries: BeuIndexEntry[],
    options?: {
      namespace?: string;
      embed?: boolean;
    },
  ): Promise<{ indexed?: number; embeddings_generated?: number }> {
    const result = await this.call("index", {
      namespace: options?.namespace || this.namespace,
      embed: options?.embed ?? false,
      entries: entries.map((entry) => ({
        ...entry,
        metadata: entry.metadata || {},
      })),
    });

    if (!result.ok) {
      throw new Error(result.error || "Index failed");
    }

    return result.data || {};
  }

  async distill(
    threadId: string,
    turnId: string,
    threadHistory: Array<{
      entry_id: string;
      kind: string;
      content: string;
      citation: string;
      created_at: string;
    }>,
    options?: {
      prior_wake_pack?: { content?: string; summary?: string };
      active_invariants?: Array<{
        id: string;
        claim: string;
        support_excerpt: string;
        falsifier: string;
      }>;
    },
  ): Promise<{
    wake_pack: { content: string; summary: string };
    facts: unknown[];
    invariant_adds: unknown[];
  }> {
    const distilledContent = threadHistory
      .map((entry) => entry.content)
      .filter((content) => content.trim().length > 0)
      .join("\n\n");
    const payload = {
      namespace: this.namespace,
      thread_id: threadId,
      turn_id: turnId,
      wake_pack: {
        content: distilledContent,
        summary: distilledContent.slice(0, 200),
      },
      facts: [],
      invariant_adds: [],
      prior_wake_pack: options?.prior_wake_pack || {},
      active_invariants: options?.active_invariants || [],
    };

    const result = await this.call("distill", payload);

    if (result instanceof jsonrpc.JsonRpcError) {
      throw new Error(result.error.message);
    }

    const data = result as {
      ok: boolean;
      data?: {
        wake_pack: { content: string; summary: string };
        facts: unknown[];
        invariant_adds: unknown[];
      };
      error?: string;
    };

    if (!data.ok) {
      throw new Error(data.error || "Distill failed");
    }

    const normalized = data.data || {};
    const indexResult = await this.call("index", {
      namespace: this.namespace,
      embed: false,
      entries: [
        {
          entry_id: turnId,
          source_type: "wake_pack",
          source_id: threadId,
          content: distilledContent,
          metadata: {
            kind: "wake_pack",
            thread_id: threadId,
            turn_id: turnId,
          },
        },
      ],
    });

    if (!indexResult.ok) {
      throw new Error(indexResult.error || "Indexing distilled memory failed");
    }

    return {
      wake_pack: normalized.wake_pack || {
        content: distilledContent,
        summary: distilledContent.slice(0, 200),
      },
      facts: normalized.facts || [],
      invariant_adds: normalized.invariant_adds || [],
    };
  }
}

let _instance: BeuProcess | null = null;

export function createBeuProcess(options?: BeuOptions): BeuProcess {
  if (!_instance) {
    _instance = new BeuProcess(options);
  }
  return _instance;
}

export function resetBeuProcess(): void {
  _instance = null;
}
