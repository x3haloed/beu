import { appendFile, mkdir, readFile, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";

const CHUNK_SIZE = 1200;
const TABLE_FILES = [
  "workspaces.jsonl",
  "agents.jsonl",
  "threads.jsonl",
  "turns.jsonl",
  "events.jsonl",
  "distill_state.jsonl",
  "ledger_entries.jsonl",
  "ledger_entry_chunks.jsonl",
];

type PluginConfig = {
  storageRoot?: string;
  namespace?: string;
};

type ContextLike = {
  sessionKey?: string;
  sessionId?: string;
  agentId?: string;
  runId?: string;
  config?: PluginConfig;
  runtimeConfig?: PluginConfig;
  cwd?: string;
};

type JsonMap = Record<string, unknown>;

function nowIso(): string {
  return new Date().toISOString();
}

function stableId(prefix: string, ...parts: unknown[]): string {
  const digest = crypto.createHash("sha1").update(parts.map(String).join("::")).digest("hex");
  return `${prefix}-${digest.slice(0, 16)}`;
}

function sanitizeNamespace(value: string): string {
  const candidate = value.trim().replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[._-]+|[._-]+$/g, "");
  if (candidate) {
    return candidate.slice(0, 80);
  }
  return `ns-${crypto.createHash("sha1").update(value).digest("hex").slice(0, 16)}`;
}

function normalizeText(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function chunkText(value: string, size = CHUNK_SIZE): string[] {
  const text = value.trim();
  if (!text) {
    return [];
  }
  const chunks: string[] = [];
  for (let index = 0; index < text.length; index += size) {
    chunks.push(text.slice(index, index + size));
  }
  return chunks;
}

async function fileExists(filePath: string): Promise<boolean> {
  try {
    await stat(filePath);
    return true;
  } catch {
    return false;
  }
}

async function ensureNamespaceFiles(namespaceDir: string): Promise<void> {
  await mkdir(namespaceDir, { recursive: true });
  for (const fileName of TABLE_FILES) {
    const filePath = path.join(namespaceDir, fileName);
    if (!(await fileExists(filePath))) {
      await appendFile(filePath, "", "utf8");
    }
  }
}

async function appendJsonl(filePath: string, record: JsonMap): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
  await appendFile(filePath, `${JSON.stringify(record)}\n`, "utf8");
}

async function readJsonl(filePath: string): Promise<JsonMap[]> {
  if (!(await fileExists(filePath))) {
    return [];
  }
  const raw = await readFile(filePath, "utf8");
  const records: JsonMap[] = [];
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed && typeof parsed === "object") {
        records.push(parsed as JsonMap);
      }
    } catch {
      continue;
    }
  }
  return records;
}

async function latestRecord(filePath: string, key: string, value: string): Promise<JsonMap | undefined> {
  const records = await readJsonl(filePath);
  let latest: JsonMap | undefined;
  for (const record of records) {
    if (String(record[key] ?? "") === value) {
      latest = record;
    }
  }
  return latest;
}

async function latestWhere(filePath: string, predicate: (record: JsonMap) => boolean): Promise<JsonMap | undefined> {
  const records = await readJsonl(filePath);
  let latest: JsonMap | undefined;
  for (const record of records) {
    if (predicate(record)) {
      latest = record;
    }
  }
  return latest;
}

function metadataFrom(source: JsonMap): JsonMap {
  const allowed = [
    "sessionId",
    "sessionKey",
    "agentId",
    "runId",
    "provider",
    "model",
    "toolCallId",
    "toolName",
    "durationMs",
    "cwd",
  ];
  const metadata: JsonMap = {};
  for (const key of allowed) {
    const value = source[key];
    if (value !== undefined && value !== null && value !== "") {
      metadata[key] = value;
    }
  }
  return metadata;
}

function summary(value: string): string | undefined {
  const text = value.trim();
  return text ? text.slice(0, 240) : undefined;
}

export class JsonlLedgerStore {
  private resolveSettings(ctx: ContextLike) {
    const pluginConfig = ctx.config ?? ctx.runtimeConfig ?? {};
    const namespace = String(pluginConfig.namespace || ctx.sessionKey || ctx.sessionId || ctx.agentId || "default");
    const storageRoot = String(
      pluginConfig.storageRoot ||
        process.env.DURABLE_LEDGER_STORAGE_ROOT ||
        path.join(os.homedir(), ".openclaw", "state", "durable-ledger"),
    );
    const namespaceDir = path.join(storageRoot, "v1", "namespaces", sanitizeNamespace(namespace));
    const workspaceRoot = String(ctx.cwd || process.cwd());
    const agentHint = String(ctx.agentId || "openclaw");
    const externalThreadId = String(ctx.sessionKey || ctx.sessionId || ctx.runId || "default");
    const channel = "openclaw";
    const workspaceId = stableId("workspace", workspaceRoot);
    const agentId = stableId("agent", workspaceId, agentHint);
    const threadId = stableId("thread", agentId, channel, externalThreadId);
    return {
      namespace,
      namespaceDir,
      workspaceRoot,
      workspaceId,
      agentId,
      threadId,
      externalThreadId,
      channel,
    };
  }

  async onLlmInput(event: JsonMap, ctx: ContextLike): Promise<void> {
    const context = this.resolveSettings(ctx);
    await ensureNamespaceFiles(context.namespaceDir);
    await this.upsertWorkspace(context);
    await this.upsertAgent(context);
    await this.upsertThread(context, String(event.prompt || event.sessionId || "OpenClaw session").slice(0, 120));
    const turnId = String(event.runId || stableId("turn", context.threadId, nowIso()));
    const userMessage = String(event.prompt || "");
    await this.upsertTurn(context, turnId, {
      status: "open",
      user_message: userMessage,
      assistant_message: null,
      error: null,
    });
    await this.appendEvent(context, turnId, "user_turn", {
      message: userMessage,
      metadata: { ...metadataFrom(event), thread_id: context.threadId },
    });
    await this.appendLedgerEntry(context, {
      id: `${turnId}:user`,
      entry_type: "user_turn",
      source_type: "user_turn",
      source_id: turnId,
      turn_id: turnId,
      title: "User turn",
      summary: summary(userMessage),
      citation: turnId,
      payload: {
        content: userMessage,
        metadata: { ...metadataFrom(event), thread_id: context.threadId },
      },
    });
    await this.appendDistillState(context, turnId, "user_turn");
  }

  async onLlmOutput(event: JsonMap, ctx: ContextLike): Promise<void> {
    const context = this.resolveSettings(ctx);
    await ensureNamespaceFiles(context.namespaceDir);
    await this.upsertWorkspace(context);
    await this.upsertAgent(context);
    await this.upsertThread(context, String(event.sessionId || "OpenClaw session"));
    const turnId = String(event.runId || (await this.resolveTurnId(context)) || stableId("turn", context.threadId, nowIso()));
    const assistantMessage = Array.isArray(event.assistantTexts)
      ? event.assistantTexts.map(String).join("\n\n")
      : String(event.assistantText || event.response || "");
    const error = event.error ? String(event.error) : undefined;
    await this.upsertTurn(context, turnId, {
      status: error ? "error" : "completed",
      assistant_message: assistantMessage || null,
      error: error || null,
    });
    if (assistantMessage) {
      await this.appendEvent(context, turnId, "assistant_turn", {
        message: assistantMessage,
        metadata: { ...metadataFrom(event), thread_id: context.threadId },
      });
      await this.appendLedgerEntry(context, {
        id: `${turnId}:assistant`,
        entry_type: "assistant_turn",
        source_type: "assistant_turn",
        source_id: turnId,
        turn_id: turnId,
        title: "Assistant turn",
        summary: summary(assistantMessage),
        citation: turnId,
        payload: {
          content: assistantMessage,
          metadata: { ...metadataFrom(event), thread_id: context.threadId },
        },
      });
    }
    if (error) {
      await this.appendEvent(context, turnId, "error", {
        error,
        metadata: { ...metadataFrom(event), thread_id: context.threadId },
      });
      await this.appendLedgerEntry(context, {
        id: `${turnId}:error`,
        entry_type: "error",
        source_type: "error",
        source_id: turnId,
        turn_id: turnId,
        title: "Turn error",
        summary: summary(error),
        citation: turnId,
        payload: {
          error,
          metadata: { ...metadataFrom(event), thread_id: context.threadId },
        },
      });
    }
    await this.appendDistillState(context, turnId, error ? "error" : "assistant_turn");
  }

  async onAfterToolCall(event: JsonMap, ctx: ContextLike): Promise<void> {
    const context = this.resolveSettings(ctx);
    await ensureNamespaceFiles(context.namespaceDir);
    await this.upsertWorkspace(context);
    await this.upsertAgent(context);
    await this.upsertThread(context, String(ctx.sessionId || "OpenClaw session"));
    const turnId = String(ctx.runId || (await this.resolveTurnId(context)) || stableId("turn", context.threadId, nowIso()));
    const toolCallId = String(event.toolCallId || event.toolName || stableId("tool", turnId, nowIso()));
    const rawResult = event.result ?? event.error ?? "";
    const serializedResult = typeof rawResult === "string" ? rawResult : JSON.stringify(rawResult);
    await this.appendEvent(context, turnId, "tool_result", {
      tool_name: event.toolName,
      tool_call_id: toolCallId,
      result: serializedResult,
      metadata: { ...metadataFrom(event), thread_id: context.threadId },
    });
    await this.appendLedgerEntry(context, {
      id: `${turnId}:tool:${toolCallId}`,
      entry_type: "tool_result",
      source_type: "tool_result",
      source_id: toolCallId,
      turn_id: turnId,
      title: `Tool result: ${String(event.toolName || "tool")}`,
      summary: summary(serializedResult),
      citation: toolCallId,
      payload: {
        tool_name: event.toolName,
        tool_call_id: toolCallId,
        result: serializedResult,
        metadata: { ...metadataFrom(event), thread_id: context.threadId },
      },
    });
    await this.appendDistillState(context, turnId, "tool_result");
  }

  private async resolveTurnId(context: ReturnType<JsonlLedgerStore["resolveSettings"]>): Promise<string | undefined> {
    const record = await latestWhere(path.join(context.namespaceDir, "distill_state.jsonl"), (candidate) => {
      return candidate.namespace_id === context.namespace && candidate.thread_id === context.threadId;
    });
    return record?.last_turn_id ? String(record.last_turn_id) : undefined;
  }

  private async upsertWorkspace(context: ReturnType<JsonlLedgerStore["resolveSettings"]>): Promise<void> {
    const filePath = path.join(context.namespaceDir, "workspaces.jsonl");
    const existing = await latestRecord(filePath, "id", context.workspaceId);
    const now = nowIso();
    await appendJsonl(filePath, {
      id: context.workspaceId,
      root: context.workspaceRoot,
      created_at: existing?.created_at ?? now,
    });
  }

  private async upsertAgent(context: ReturnType<JsonlLedgerStore["resolveSettings"]>): Promise<void> {
    const filePath = path.join(context.namespaceDir, "agents.jsonl");
    const existing = await latestRecord(filePath, "id", context.agentId);
    const now = nowIso();
    await appendJsonl(filePath, {
      id: context.agentId,
      display_name: "OpenClaw Durable Ledger",
      workspace_id: context.workspaceId,
      created_at: existing?.created_at ?? now,
    });
  }

  private async upsertThread(context: ReturnType<JsonlLedgerStore["resolveSettings"]>, title: string): Promise<void> {
    const filePath = path.join(context.namespaceDir, "threads.jsonl");
    const existing = await latestRecord(filePath, "id", context.threadId);
    const now = nowIso();
    await appendJsonl(filePath, {
      id: context.threadId,
      agent_id: context.agentId,
      channel: context.channel,
      external_thread_id: context.externalThreadId,
      title: title || "OpenClaw session",
      metadata_json: JSON.stringify({ namespace: context.namespace, workspace_root: context.workspaceRoot }),
      created_at: existing?.created_at ?? now,
      updated_at: now,
    });
  }

  private async upsertTurn(
    context: ReturnType<JsonlLedgerStore["resolveSettings"]>,
    turnId: string,
    update: { status?: string; user_message?: string | null; assistant_message?: string | null; error?: string | null },
  ): Promise<void> {
    const filePath = path.join(context.namespaceDir, "turns.jsonl");
    const existing = (await latestRecord(filePath, "id", turnId)) ?? {};
    const now = nowIso();
    await appendJsonl(filePath, {
      id: turnId,
      thread_id: context.threadId,
      status: update.status ?? existing.status ?? "open",
      user_message: update.user_message ?? existing.user_message ?? "",
      assistant_message: update.assistant_message ?? existing.assistant_message ?? null,
      error: update.error ?? existing.error ?? null,
      created_at: existing.created_at ?? now,
      updated_at: now,
    });
  }

  private async appendEvent(
    context: ReturnType<JsonlLedgerStore["resolveSettings"]>,
    turnId: string,
    kind: string,
    payload: JsonMap,
  ): Promise<void> {
    const filePath = path.join(context.namespaceDir, "events.jsonl");
    const records = await readJsonl(filePath);
    let sequence = 1;
    for (const record of records) {
      if (String(record.turn_id ?? "") === turnId) {
        sequence = Math.max(sequence, Number(record.sequence ?? 0) + 1);
      }
    }
    await appendJsonl(filePath, {
      id: stableId("event", turnId, sequence, nowIso()),
      turn_id: turnId,
      thread_id: context.threadId,
      sequence,
      kind,
      payload: JSON.stringify(payload),
      created_at: nowIso(),
    });
  }

  private async appendDistillState(
    context: ReturnType<JsonlLedgerStore["resolveSettings"]>,
    turnId: string,
    eventKind: string,
  ): Promise<void> {
    const filePath = path.join(context.namespaceDir, "distill_state.jsonl");
    const existing = await latestWhere(filePath, (record) => {
      return record.namespace_id === context.namespace && record.thread_id === context.threadId;
    });
    await appendJsonl(filePath, {
      namespace_id: context.namespace,
      thread_id: context.threadId,
      hook_count: Number(existing?.hook_count ?? 0) + 1,
      last_turn_id: turnId,
      last_event_kind: eventKind,
      last_distilled_at: existing?.last_distilled_at ?? null,
      updated_at: nowIso(),
    });
  }

  private async appendLedgerEntry(
    context: ReturnType<JsonlLedgerStore["resolveSettings"]>,
    params: {
      id: string;
      entry_type: string;
      source_type: string;
      source_id: string;
      turn_id: string;
      title: string;
      summary?: string;
      citation: string;
      payload: JsonMap;
    },
  ): Promise<void> {
    const filePath = path.join(context.namespaceDir, "ledger_entries.jsonl");
    const existing = await latestRecord(filePath, "id", params.id);
    const now = nowIso();
    const payloadJson = JSON.stringify(params.payload);
    await appendJsonl(filePath, {
      id: params.id,
      namespace_id: context.namespace,
      entry_type: params.entry_type,
      source_type: params.source_type,
      source_id: params.source_id,
      thread_id: context.threadId,
      turn_id: params.turn_id,
      title: params.title,
      summary: params.summary ?? null,
      citation: params.citation,
      payload_json: payloadJson,
      importance: 0,
      created_at: existing?.created_at ?? now,
      updated_at: now,
      deleted_at: null,
    });

    const content = [params.title, params.summary ?? "", payloadJson].filter(Boolean).join("\n\n");
    const hintsJson = JSON.stringify({
      entry_type: params.entry_type,
      source_type: params.source_type,
      source_id: params.source_id,
    });
    const chunksPath = path.join(context.namespaceDir, "ledger_entry_chunks.jsonl");
    const chunks = chunkText(content);
    for (let index = 0; index < chunks.length; index += 1) {
      const chunk = chunks[index];
      await appendJsonl(chunksPath, {
        chunk_id: stableId("chunk", params.id, index, now),
        namespace_id: context.namespace,
        entry_id: params.id,
        chunk_index: index,
        content: chunk,
        content_norm: normalizeText(chunk),
        search_hints_json: hintsJson,
        created_at: now,
        updated_at: now,
      });
    }
  }
}