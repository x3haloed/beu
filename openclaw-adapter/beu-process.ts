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

  private async call(command: string, payload: Record<string, unknown>): Promise<jsonrpc.JsonRpcObject> {
    return new Promise((resolve, reject) => {
      const request = jsonrpc.request(command, {
        version: "1.0.0",
        command,
        id: `${command}-${Date.now()}`,
        namespace: this.namespace,
        payload,
      });

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
          const response = JSON.parse(stdout.trim());
          resolve(response);
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

    const response = await this.call("recall", payload);

    if (response instanceof jsonrpc.JsonRpcError) {
      throw new Error(response.error.message);
    }

    const result = response.payload as { ok: boolean; data?: { hits: BeuRecallHit[] }; error?: string };

    if (!result.ok) {
      throw new Error(result.error || "Recall failed");
    }

    return result.data?.hits || [];
  }

  async identity(query: string = "all"): Promise<BeuIdentityResult> {
    const payload = { query, limit: 10 };

    const response = await this.call("identity", payload);

    if (response instanceof jsonrpc.JsonRpcError) {
      throw new Error(response.error.message);
    }

    const result = response.payload as { ok: boolean; data?: BeuIdentityResult; error?: string };

    if (!result.ok) {
      throw new Error(result.error || "Identity query failed");
    }

    return result.data || { invariants: [] };
  }

  async status(): Promise<BeuStatusResult> {
    const payload = {};

    const response = await this.call("status", payload);

    if (response instanceof jsonrpc.JsonRpcError) {
      throw new Error(response.error.message);
    }

    const result = response.payload as { ok: boolean; data?: BeuStatusResult; error?: string };

    if (!result.ok) {
      throw new Error(result.error || "Status check failed");
    }

    return result.data || { storage: "unknown" };
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
    const payload = {
      thread_id: threadId,
      turn_id: turnId,
      thread_history: threadHistory,
      prior_wake_pack: options?.prior_wake_pack || {},
      active_invariants: options?.active_invariants || [],
    };

    const response = await this.call("distill", payload);

    if (response instanceof jsonrpc.JsonRpcError) {
      throw new Error(response.error.message);
    }

    const result = response.payload as {
      ok: boolean;
      data?: {
        wake_pack: { content: string; summary: string };
        facts: unknown[];
        invariant_adds: unknown[];
      };
      error?: string;
    };

    if (!result.ok) {
      throw new Error(result.error || "Distill failed");
    }

    return result.data || {
      wake_pack: { content: "", summary: "" },
      facts: [],
      invariant_adds: [],
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
