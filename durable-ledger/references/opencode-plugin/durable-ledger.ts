import { appendFile, mkdir, readFile, stat } from "node:fs/promises";
import crypto from "node:crypto";
import os from "node:os";
import path from "node:path";

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

const CHUNK_SIZE = 1200;

type JsonMap = Record<string, unknown>;

type PluginContext = {
  project?: { name?: string };
  directory?: string;
  worktree?: string;
  client?: {
    app?: {
      log?: (entry: { body: JsonMap }) => Promise<unknown>;
    };
  };
};

type HookMap = {
  event: (input: { event: JsonMap }) => Promise<void>;
};

type StoreContext = {
  sessionKey?: string;
  sessionId?: string;
  agentHint: string;
  workspaceRoot: string;
};

function nowIso(): string {
  return new Date().toISOString();
}

function stableId(prefix: string, ...parts: unknown[]): string {
  const digest = crypto.createHash("sha1").update(parts.map(String).join("::")).digest("hex");
  return `${prefix}-${digest.slice(0, 16)}`;
}

function sanitizeNamespace(value: string): string {
  const candidate = value
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/^[._-]+|[._-]+$/g, "");

  if (candidate) {
    return candidate.slice(0, 80);
  }

  return `ns-${crypto.createHash("sha1").update(value).digest("hex").slice(0, 16)}`;
}

function normalizeText(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function summarize(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, 240) : undefined;
}

function chunkText(value: string): string[] {
  const trimmed = value.trim();
  if (!trimmed) {
    return [];
  }

  const chunks: string[] = [];
  for (let index = 0; index < trimmed.length; index += CHUNK_SIZE) {
    chunks.push(trimmed.slice(index, index + CHUNK_SIZE));
  }
  return chunks;
}

function getStorageRoot(): string {
  return process.env.DURABLE_LEDGER_STORAGE_ROOT || path.join(os.homedir(), ".config", "opencode", "state", "durable-ledger");
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

function getObject(value: unknown): JsonMap | undefined {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as JsonMap;
  }
  return undefined;
}

function getString(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }

  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

function getTextFromParts(parts: unknown): string | undefined {
  if (!Array.isArray(parts)) {
    return undefined;
  }

  const values = parts
    .map((part) => {
      const item = getObject(part);
      if (!item) {
        return undefined;
      }
      return getString(item.text) || getString(item.content);
    })
    .filter((value): value is string => Boolean(value));

  if (!values.length) {
    return undefined;
  }

  return values.join("\n\n");
}

function getMessageText(event: JsonMap): string | undefined {
  const message = getObject(event.message);
  const response = getObject(event.response);

  return (
    getString(event.text) ||
    getString(event.content) ||
    getString(event.summary) ||
    getString(event.response) ||
    getString(message?.text) ||
    getString(message?.content) ||
    getTextFromParts(message?.parts) ||
    getString(response?.text) ||
    getString(response?.content) ||
    getTextFromParts(response?.parts)
  );
}

function getRole(event: JsonMap): string | undefined {
  const message = getObject(event.message);
  const response = getObject(event.response);
  return getString(event.role) || getString(message?.role) || getString(response?.role);
}

function getSessionKey(event: JsonMap): string {
  return String(
    event.sessionId ||
      event.session_id ||
      event.id ||
      getObject(event.session)?.id ||
      process.env.DURABLE_LEDGER_NAMESPACE ||
      "default",
  );
}

function metadataFrom(event: JsonMap, eventType: string, workspaceRoot: string): JsonMap {
  const metadata: JsonMap = {
    event_type: eventType,
    cwd: workspaceRoot,
  };

  const allowed = [
    "sessionId",
    "session_id",
    "id",
    "toolCallId",
    "tool_call_id",
    "toolName",
    "tool",
    "provider",
    "model",
    "durationMs",
    "duration_ms",
  ];

  for (const key of allowed) {
    const value = event[key];
    if (value !== undefined && value !== null && value !== "") {
      metadata[key] = value;
    }
  }

  return metadata;
}

class JsonlLedgerStore {
  private resolveContext(ctx: StoreContext) {
    const sessionKey = String(ctx.sessionKey || ctx.sessionId || "default");
    const namespace = sanitizeNamespace(process.env.DURABLE_LEDGER_NAMESPACE || sessionKey || ctx.agentHint || "default");
    const storageRoot = getStorageRoot();
    const namespaceDir = path.join(storageRoot, "v1", "namespaces", namespace);
    const workspaceRoot = ctx.workspaceRoot;
    const workspaceId = stableId("workspace", workspaceRoot);
    const agentId = stableId("agent", workspaceId, ctx.agentHint || "opencode");
    const threadId = stableId("thread", agentId, "opencode", sessionKey);

    return {
      namespace,
      namespaceDir,
      workspaceRoot,
      workspaceId,
      agentId,
      threadId,
      sessionKey,
      agentHint: ctx.agentHint,
    };
  }

  async touchSession(ctx: StoreContext, title: string): Promise<void> {
    const context = this.resolveContext(ctx);
    await ensureNamespaceFiles(context.namespaceDir);
    await this.upsertWorkspace(context);
    await this.upsertAgent(context);
    await this.upsertThread(context, title || "OpenCode session");
  }

  async onUserMessage(event: JsonMap, ctx: StoreContext, eventType: string, message: string): Promise<void> {
    const context = this.resolveContext(ctx);
    await ensureNamespaceFiles(context.namespaceDir);
    await this.upsertWorkspace(context);
    await this.upsertAgent(context);
    await this.upsertThread(context, message.slice(0, 120) || "OpenCode session");

    const turnId = String(event.runId || event.messageId || stableId("turn", context.threadId, nowIso()));
    const metadata = metadataFrom(event, eventType, context.workspaceRoot);

    await this.upsertTurn(context, turnId, {
      status: "open",
      user_message: message,
      assistant_message: null,
      error: null,
    });

    await this.appendEvent(context, turnId, "user_turn", {
      message,
      metadata,
    });

    await this.appendLedgerEntry(context, {
      id: `${turnId}:user`,
      entry_type: "user_turn",
      source_type: "user_turn",
      source_id: turnId,
      turn_id: turnId,
      title: "User turn",
      summary: summarize(message),
      citation: turnId,
      payload: {
        content: message,
        metadata,
      },
    });

    await this.appendDistillState(context, turnId, "user_turn");
  }

  async onAssistantMessage(event: JsonMap, ctx: StoreContext, eventType: string, message: string, error?: string): Promise<void> {
    const context = this.resolveContext(ctx);
    await ensureNamespaceFiles(context.namespaceDir);
    await this.upsertWorkspace(context);
    await this.upsertAgent(context);
    await this.upsertThread(context, "OpenCode session");

    const turnId = String(event.runId || (await this.resolveTurnId(context)) || stableId("turn", context.threadId, nowIso()));
    const metadata = metadataFrom(event, eventType, context.workspaceRoot);

    await this.upsertTurn(context, turnId, {
      status: error ? "error" : "completed",
      user_message: undefined,
      assistant_message: message || null,
      error: error || null,
    });

    if (message) {
      await this.appendEvent(context, turnId, "assistant_turn", {
        message,
        metadata,
      });

      await this.appendLedgerEntry(context, {
        id: `${turnId}:assistant`,
        entry_type: "assistant_turn",
        source_type: "assistant_turn",
        source_id: turnId,
        turn_id: turnId,
        title: "Assistant turn",
        summary: summarize(message),
        citation: turnId,
        payload: {
          content: message,
          metadata,
        },
      });
    }

    if (error) {
      await this.appendEvent(context, turnId, "error", {
        error,
        metadata,
      });

      await this.appendLedgerEntry(context, {
        id: `${turnId}:error`,
        entry_type: "error",
        source_type: "error",
        source_id: turnId,
        turn_id: turnId,
        title: "Session error",
        summary: summarize(error),
        citation: turnId,
        payload: {
          error,
          metadata,
        },
      });
    }

    await this.appendDistillState(context, turnId, error ? "error" : "assistant_turn");
  }

  async onToolResult(event: JsonMap, ctx: StoreContext, eventType: string): Promise<void> {
    const context = this.resolveContext(ctx);
    await ensureNamespaceFiles(context.namespaceDir);
    await this.upsertWorkspace(context);
    await this.upsertAgent(context);
    await this.upsertThread(context, "OpenCode session");

    const turnId = String(event.runId || (await this.resolveTurnId(context)) || stableId("turn", context.threadId, nowIso()));
    const toolName = String(event.tool || event.toolName || "tool");
    const toolCallId = String(event.toolCallId || event.tool_call_id || stableId("tool", turnId, toolName, nowIso()));
    const resultValue = event.result ?? event.output ?? event.error ?? "";
    const result = typeof resultValue === "string" ? resultValue : JSON.stringify(resultValue);
    const metadata = metadataFrom(event, eventType, context.workspaceRoot);

    await this.appendEvent(context, turnId, "tool_result", {
      tool_name: toolName,
      tool_call_id: toolCallId,
      result,
      metadata,
    });

    await this.appendLedgerEntry(context, {
      id: `${turnId}:tool:${toolCallId}`,
      entry_type: "tool_result",
      source_type: "tool_result",
      source_id: toolCallId,
      turn_id: turnId,
      title: `Tool result: ${toolName}`,
      summary: summarize(result),
      citation: toolCallId,
      payload: {
        tool_name: toolName,
        tool_call_id: toolCallId,
        result,
        metadata,
      },
    });

    await this.appendDistillState(context, turnId, "tool_result");
  }

  private async resolveTurnId(context: ReturnType<JsonlLedgerStore["resolveContext"]>): Promise<string | undefined> {
    const record = await latestWhere(path.join(context.namespaceDir, "distill_state.jsonl"), (candidate) => {
      return String(candidate.namespace_id ?? "") === context.namespace && String(candidate.thread_id ?? "") === context.threadId;
    });
    return getString(record?.last_turn_id);
  }

  private async upsertWorkspace(context: ReturnType<JsonlLedgerStore["resolveContext"]>): Promise<void> {
    const filePath = path.join(context.namespaceDir, "workspaces.jsonl");
    const existing = await latestRecord(filePath, "id", context.workspaceId);
    const now = nowIso();
    await appendJsonl(filePath, {
      id: context.workspaceId,
      root: context.workspaceRoot,
      created_at: existing?.created_at ?? now,
    });
  }

  private async upsertAgent(context: ReturnType<JsonlLedgerStore["resolveContext"]>): Promise<void> {
    const filePath = path.join(context.namespaceDir, "agents.jsonl");
    const existing = await latestRecord(filePath, "id", context.agentId);
    const now = nowIso();
    await appendJsonl(filePath, {
      id: context.agentId,
      display_name: context.agentHint,
      workspace_id: context.workspaceId,
      created_at: existing?.created_at ?? now,
    });
  }

  private async upsertThread(context: ReturnType<JsonlLedgerStore["resolveContext"]>, title: string): Promise<void> {
    const filePath = path.join(context.namespaceDir, "threads.jsonl");
    const existing = await latestRecord(filePath, "id", context.threadId);
    const now = nowIso();
    await appendJsonl(filePath, {
      id: context.threadId,
      agent_id: context.agentId,
      channel: "opencode",
      external_thread_id: context.sessionKey,
      title: title || "OpenCode session",
      metadata_json: JSON.stringify({
        namespace: context.namespace,
        workspace_root: context.workspaceRoot,
      }),
      created_at: existing?.created_at ?? now,
      updated_at: now,
    });
  }

  private async upsertTurn(
    context: ReturnType<JsonlLedgerStore["resolveContext"]>,
    turnId: string,
    update: {
      status?: string;
      user_message?: string | null;
      assistant_message?: string | null;
      error?: string | null;
    },
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
    context: ReturnType<JsonlLedgerStore["resolveContext"]>,
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
    context: ReturnType<JsonlLedgerStore["resolveContext"]>,
    turnId: string,
    eventKind: string,
  ): Promise<void> {
    const filePath = path.join(context.namespaceDir, "distill_state.jsonl");
    const existing = await latestWhere(filePath, (record) => {
      return String(record.namespace_id ?? "") === context.namespace && String(record.thread_id ?? "") === context.threadId;
    });
    const now = nowIso();

    await appendJsonl(filePath, {
      namespace_id: context.namespace,
      thread_id: context.threadId,
      last_turn_id: turnId,
      last_event_kind: eventKind,
      summary_text: existing?.summary_text ?? null,
      updated_at: now,
      created_at: existing?.created_at ?? now,
    });
  }

  private async appendLedgerEntry(context: ReturnType<JsonlLedgerStore["resolveContext"]>, entry: JsonMap): Promise<void> {
    const entryFile = path.join(context.namespaceDir, "ledger_entries.jsonl");
    const chunkFile = path.join(context.namespaceDir, "ledger_entry_chunks.jsonl");
    const now = nowIso();
    const payload = getObject(entry.payload) ?? {};
    const content = getString(payload.content) || getString(payload.result) || getString(payload.error) || "";

    await appendJsonl(entryFile, {
      ...entry,
      namespace_id: context.namespace,
      thread_id: context.threadId,
      created_at: now,
    });

    const normalized = normalizeText(content);
    const chunks = chunkText(content);
    for (let index = 0; index < chunks.length; index += 1) {
      await appendJsonl(chunkFile, {
        id: stableId("chunk", String(entry.id), index),
        entry_id: entry.id,
        namespace_id: context.namespace,
        thread_id: context.threadId,
        chunk_index: index,
        content: chunks[index],
        normalized_content: normalized,
        created_at: now,
      });
    }
  }
}

const store = new JsonlLedgerStore();

async function logInfo(client: PluginContext["client"], message: string, extra: JsonMap = {}): Promise<void> {
  const log = client?.app?.log;
  if (!log) {
    return;
  }

  await log({
    body: {
      service: "durable-ledger",
      level: "info",
      message,
      extra,
    },
  });
}

function toStoreContext(pluginContext: PluginContext, event: JsonMap): StoreContext {
  return {
    sessionKey: getSessionKey(event),
    sessionId: getString(event.sessionId) || getString(event.session_id),
    agentHint: pluginContext.project?.name || "OpenCode Durable Ledger",
    workspaceRoot: pluginContext.directory || pluginContext.worktree || process.cwd(),
  };
}

function isUserMessageEvent(eventType: string, role?: string): boolean {
  if (eventType === "message.updated") {
    return role !== "assistant";
  }

  return eventType === "session.updated" && role !== "assistant";
}

function isAssistantEvent(eventType: string, role?: string): boolean {
  if (eventType === "message.updated") {
    return role === "assistant";
  }

  return eventType === "session.idle" || eventType === "session.compacted";
}

export const DurableLedgerPlugin = async (pluginContext: PluginContext): Promise<HookMap> => {
  await logInfo(pluginContext.client, "Durable ledger plugin initialized", {
    storageRoot: getStorageRoot(),
  });

  return {
    event: async ({ event }) => {
      const eventType = getString(event.type);
      if (!eventType) {
        return;
      }

      const ctx = toStoreContext(pluginContext, event);

      if (eventType === "session.created") {
        await store.touchSession(ctx, "OpenCode session");
        return;
      }

      if (eventType === "tool.execute.after") {
        await store.onToolResult(event, ctx, eventType);
        return;
      }

      if (eventType === "session.error") {
        const errorText = getString(event.error) || getMessageText(event) || "Session error";
        await store.onAssistantMessage(event, ctx, eventType, "", errorText);
        return;
      }

      const role = getRole(event);
      const messageText = getMessageText(event);
      if (!messageText) {
        return;
      }

      if (isUserMessageEvent(eventType, role)) {
        await store.onUserMessage(event, ctx, eventType, messageText);
        return;
      }

      if (isAssistantEvent(eventType, role)) {
        await store.onAssistantMessage(event, ctx, eventType, messageText);
      }
    },
  };
};

export default DurableLedgerPlugin;