import { spawn } from "child_process";

const DEFAULT_BINARY = "beu";

export interface BeuOptions {
  binaryPath?: string;
  namespace?: string;
}

export interface BeuIndexEntry {
  entry_id: string;
  source_type: string;
  source_id: string;
  content: string;
  metadata?: Record<string, unknown>;
}

export interface BeuEmbeddingProvider {
  provider: string;
  model: string;
  base_url?: string;
  api_key?: string;
  headers?: Record<string, string>;
  output_dimensionality?: number;
}

export interface LedgerEntry {
  entry_id: string;
  thread_id: string;
  turn_id: string;
  created_at: string;
  citation: string;
  content: string;
  payload?: unknown;
}

export interface BeuIdentityResult {
  invariants: Array<{
    id: string;
    claim: string;
    status: string;
  }>;
}

export interface BeuStatusResult {
  storage: string;
  embedding_available?: boolean;
  vector_available?: boolean;
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

  async index(
    entries: BeuIndexEntry[],
    options?: {
      namespace?: string;
      embed?: boolean;
      embeddingProvider?: BeuEmbeddingProvider;
    },
  ): Promise<{ indexed?: number; embeddings_generated?: number }> {
    return this.call("index", {
      namespace: options?.namespace || this.namespace,
      embed: options?.embed ?? false,
      embedding_provider: options?.embeddingProvider,
      entries: entries.map((entry) => ({
        ...entry,
        metadata: entry.metadata || {},
      })),
    });
  }

  async identity(query: string = "all"): Promise<BeuIdentityResult> {
    return { invariants: [] };
  }

  async status(): Promise<BeuStatusResult> {
    return {
      storage: "memory",
      embedding_available: false,
      vector_available: false,
    };
  }

  ledgerList(options: {
    thread_id?: string;
    limit?: number;
  }): Promise<any> {
    return this.call("ledger_list", {
      namespace: this.namespace,
      thread_id: options.thread_id,
      limit: options.limit ?? 20,
    });
  }

  ledgerSearch(options: {
    query: string;
    thread_id?: string;
    limit?: number;
  }): Promise<any> {
    return this.call("ledger_search", {
      namespace: this.namespace,
      query: options.query,
      thread_id: options.thread_id,
      limit: options.limit ?? 8,
    });
  }

  ledgerGet(entryId: string): Promise<any> {
    return this.call("ledger_get", {
      namespace: this.namespace,
      entry_id: entryId,
    });
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
