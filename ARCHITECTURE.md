# BeU Architecture (Detailed)

> This document maps the host requirements to the BeU design, establishing the contract between adapters and the core binary.

## Host Requirements Analysis

### OpenClaw (TypeScript)

OpenClaw treats memory plugins as first-class capabilities with exclusive slots. A memory plugin must provide:

**1. Memory Prompt Section Builder**
```typescript
type MemoryPromptSectionBuilder = (params: {
  availableTools: Set<string>;
  citationsMode?: MemoryCitationsMode;
}) => string[];
```
- Called during prompt construction
- Returns text sections to inject into system prompt
- Called on every turn

**2. Memory Flush Plan Resolver**
```typescript
type MemoryFlushPlanResolver = (params: {
  cfg?: OpenClawConfig;
  nowMs?: number;
}) => MemoryFlushPlan | null;
```
- Determines when context should be flushed to memory
- Returns: softThresholdTokens, forceFlushTranscriptBytes, prompt, systemPrompt, relativePath

**3. Memory Plugin Runtime**
```typescript
type MemoryPluginRuntime = {
  getMemorySearchManager(params: {
    cfg: OpenClawConfig;
    agentId: string;
    purpose?: "default" | "status";
  }): Promise<{
    manager: RegisteredMemorySearchManager | null;
    error?: string;
  }>;
  
  resolveMemoryBackendConfig(params: {
    cfg: OpenClawConfig;
    agentId: string;
  }): MemoryRuntimeBackendConfig;
};
```

The `MemorySearchManager` provides:
- `status()` - provider status
- `probeEmbeddingAvailability()` - can we embed?
- `probeVectorAvailability()` - can we search vectors?
- `sync(params?)` - sync embeddings to vector store
- `close()` - cleanup

**4. Memory Embedding Provider**
- Provides embedding generation for content
- Must implement `embed(text) => number[]`

**5. Tools**
- `memory_search` - Search raw turn content
- `memory_get` - Retrieve specific memories

### Hermes-agent (Python)

Hermes treats plugins as hookable components. A memory plugin must provide:

**1. Tools**
```python
ctx.register_tool(
    name="memory_search",
    toolset="memory",
    schema={...},  # JSON schema for LLM
    handler=handler_func,
)
```

**2. Lifecycle Hooks**
```python
ctx.register_hook("pre_llm_call", callback)
ctx.register_hook("post_llm_call", callback)
ctx.register_hook("pre_tool_call", callback)
ctx.register_hook("post_tool_call", callback)
ctx.register_hook("on_session_start", callback)
ctx.register_hook("on_session_end", callback)
```

Each hook receives context (messages, model, tool_name, args, result, session_id, etc.)

---

## BetterClaw System (The Reference Implementation)

The system we're porting from betterclaw-legacy:

```
┌─────────────────────────────────────────────────────────────────┐
│                      Runtime (Rust)                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐   │
│  │    Turn      │───▶│  Canonical Ledger │──▶│    Store     │   │
│  │   Ingest     │    │   + Search Units  │    │  (libsql)    │   │
│  └──────────────┘    └──────────────────┘    └──────────────┘   │
│         │                     │                   │              │
│         │                     │                   ▼              │
│         │                     │          ┌──────────────┐        │
│         │                     └─────────▶│   Recall     │        │
│         │                                │   (Search)   │        │
│         │                                └──────────────┘        │
│         │                                      │                 │
│         ▼                                      ▼                 │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                    Ledger Entries                         │    │
│  │  - user_turn   - agent_turn   - tool_call               │    │
│  │  - tool_result  - error       - trace_summary           │    │
│  └──────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │            Search Units (chunk-level)                     │    │
│  │  - FTS index    - native vector column + index           │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Key Components:**

1. **Turn Ingest** - Normalize turns into ledger entries
2. **Store** - SQLite (libsql) for structured data
3. **Recall** - Hybrid search over chunked raw turn entries using FTS plus native vectors
4. **Embeddings** - Stored alongside chunked raw-turn search units using libsql vector columns

---

## BeU Architecture

### Design Decision: Stateful Adapter, Stateless Core

The binary is stateless. The adapter is stateful. This matches the Claude Code tool model.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Adapter (Long-Lived)                     │
│  - Spawns binary once, keeps it alive                            │
│  - Manages: namespace, caching, binary lifecycle                │
│  - Implements: host plugin API                                   │
├─────────────────────────────────────────────────────────────────┤
│                         STDIO Protocol                          │
│                     (JSON request/response)                     │
├─────────────────────────────────────────────────────────────────┤
│                      Binary (Stateless)                         │
│  - No memory between calls                                       │
│  - All state in external storage                                 │
│  - Pure business logic                                           │
└─────────────────────────────────────────────────────────────────┘
```

### Adapter Responsibilities

The adapter is the "glue" - it implements what the host expects while delegating to the binary.

For Hermes specifically, one likely onboarding path is a setup script that writes the host's Honcho config and enables "honcho mode" for the Hermes peer. That would suppress local `MEMORY.md` writes for that peer while leaving the BeU adapter in control of memory behavior, without requiring changes to hermes-agent itself.

**For OpenClaw:**
```
┌─────────────────────────────────────────────┐
│            beu-openclaw (Adapter)           │
├─────────────────────────────────────────────┤
│                                             │
│  register(api):                             │
│    - registerMemoryPromptSection(builder)  │────┐
│    - registerMemoryFlushPlan(resolver)     │    │
│    - registerMemoryRuntime(runtime)        │    │
│    - registerMemoryEmbeddingProvider()    │    │
│    - registerTool(memory_search)           │    │
│    - registerTool(memory_get)              │    │
│                                             │    ▼
│                           ┌─────────────────┴──────┐
│                           │   beu binary (spawned)  │
│                           │   STDIO JSON            │
│                           └─────────────────────────┘
└─────────────────────────────────────────────┘
```

**For Hermes:**
```
┌─────────────────────────────────────────────┐
│              beu-hermes (Adapter)           │
├─────────────────────────────────────────────┤
│                                             │
│  register(ctx):                             │
│    - register_tool(memory_search)           │────┐
│    - register_tool(memory_distill)          │    │
│    - register_hook(pre_llm_call)            │    │
│    - register_hook(post_llm_call)          │    │
│    - register_hook(on_session_start)       │    │
│    - register_hook(on_session_end)         │    │
│                                             │    ▼
│                           ┌─────────────────┴──────┐
│                           │   beu binary (spawned)  │
│                           │   STDIO JSON            │
│                           └─────────────────────────┘
└─────────────────────────────────────────────┘
```

### Binary Commands (What Adapters Call)

The binary exposes these commands via STDIO:

| Command | OpenClaw Use | Hermes Use | Description |
|---------|--------------|------------|--------------|
| `distill` | Flush plan triggers | post_llm_call hook | Compress turn to memory |
| `recall` | memory_search tool | memory_search tool | Search raw turn content |
| `rebuild` | CLI / init | CLI / init | Full rebuild from history |
| `identity` | Prompt section build | pre_llm_call hook | Get agent identity |
| `index` | sync() called | (batch) | Index new content |

### Data Flow: OpenClaw Example

```
Turn happens
    │
    ▼
OpenClaw calls memory_search tool
    │
    ▼
Adapter sends recall command to binary
    │
    ▼
Binary queries raw-turn search units, returns hits
    │
    ▼
Adapter formats as tool result, returns to OpenClaw
```

```
Context flush triggers
    │
    ▼
registerMemoryFlushPlan resolver fires
    │
    ▼
Adapter sends distill command to binary
    │
    ▼
Binary compresses, stores, returns wake_pack
    │
    ▼
Adapter uses result to write to memory file
```

### Data Flow: Hermes Example

```
LLM call about to happen
    │
    ▼
pre_llm_call hook fires
    │
    ▼
Adapter sends identity command to binary
    │
    ▼
Binary returns active invariants
    │
    ▼
Adapter injects into messages, returns
```

```
Tool called
    │
    ▼
post_tool_call hook fires
    │
    ▼
Adapter sends distill command to binary
    │
    ▼
Binary extracts facts, returns
    │
    ▼
Adapter stores results (if configurable)
```

---

## Storage Design

The binary is storage-agnostic. Default implementation:

```
beu_data/
├── config.json          # Global config
├── namespaces/
│   └── default/
│       ├── memory.db    # SQLite (facts, invariants, drift)
│       ├── wakepacks/  # Wake pack files
│       ├── embeddings/ # Vector store (or embedded in DB)
│       └── ledger/     # Raw ledger entries
└── cache/               # Runtime cache
```

### SQLite Schema (from BetterClaw)

```sql
-- Facts: atomic observations
CREATE TABLE memory_facts (
  id TEXT PRIMARY KEY,
  namespace_id TEXT NOT NULL,
  claim TEXT NOT NULL,
  support_excerpt TEXT NOT NULL,
  falsifier TEXT NOT NULL,
  confidence REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Fact to ledger entry citations
CREATE TABLE memory_fact_evidence (
  fact_id TEXT,
  entry_id TEXT
);

-- Invariants: generalized truths
CREATE TABLE memory_invariants (
  id TEXT PRIMARY KEY,
  namespace_id TEXT NOT NULL,
  claim TEXT NOT NULL,
  support_excerpt TEXT NOT NULL,
  falsifier TEXT NOT NULL,
  status TEXT NOT NULL, -- 'active' | 'superseded'
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Invariant supersession
CREATE TABLE memory_invariant_supersedes (
  invariant_id TEXT,
  superseded_invariant_id TEXT
);

-- Drift detection items
CREATE TABLE memory_drift_items (
  id TEXT PRIMARY KEY,
  namespace_id TEXT NOT NULL,
  kind TEXT NOT NULL, -- 'flag', 'contradiction', 'merge'
  claim TEXT NOT NULL,
  support_excerpt TEXT,
  falsifier TEXT,
  citations_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Recall chunks with embeddings
CREATE TABLE memory_recall_chunks (
  chunk_id TEXT PRIMARY KEY,
  namespace_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  entry_id TEXT NOT NULL,
  chunk_index INTEGER,
  content TEXT NOT NULL,
  embedding_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- FTS for recall
CREATE VIRTUAL TABLE memory_recall_chunks_fts USING fts5(
  chunk_id, namespace_id, source_type, source_id, entry_id, content
);

-- Wake packs
CREATE TABLE wake_packs (
  id TEXT PRIMARY KEY,
  namespace_id TEXT NOT NULL,
  content TEXT NOT NULL,
  summary TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

---

## Error Handling

All responses follow this schema:

```json
{
  "version": "1.0.0",
  "id": "request-uuid",
  "ok": true,
  "data": { ... }
}
```

```json
{
  "version": "1.0.0", 
  "id": "request-uuid",
  "ok": false,
  "error": "human readable",
  "code": "ERROR_CODE"
}
```

Error codes:
- `INVALID_REQUEST` - Malformed JSON or missing fields
- `UNKNOWN_COMMAND` - Command not recognized
- `STORAGE_ERROR` - DB/filesystem failure
- `MODEL_ERROR` - LLM call failed
- `NOT_FOUND` - Resource missing
- `NAMESPACE_CONFLICT` - Already exists

---

## Versioning

- Protocol is versioned via `version` field
- Clients declare expected version in requests
- Server responds with same version (or closest compatible)
- Backward compatibility maintained

---

## Adapter Implementation Notes

### OpenClaw Adapter

```typescript
// The adapter wraps the binary and implements MemoryPluginRuntime
class BeUMemoryRuntime {
  async getMemorySearchManager({ cfg, agentId }) {
    // Spawn binary if not running
    // Return manager that calls binary recall
  }
}

// Also implements MemoryFlushPlanResolver
// Also implements MemoryPromptSectionBuilder
// Also registers tools
```

### Hermes Adapter

```python
# The adapter hooks into lifecycle
def on_pre_llm_call(messages, model, **kwargs):
    # Call binary identity
    # Inject into messages
    
def on_post_tool_call(tool_name, args, result, **kwargs):
    # Call binary distill (if configured)
```

### Key Insight: Caching

Both adapters should implement caching:
- Keep binary process alive between calls
- Cache embeddings if possible
- Cache last identity/invariants for quick retrieval

This gives "long-lived" behavior while maintaining "stateless core" principle.

---

## Multi-Agent Identity Isolation

### OpenClaw

OpenClaw supports multiple agents with separate memory stores. Each agent has its own database file:

```
~/.openclaw/memory/{agentId}.sqlite
```

The `MemoryPluginRuntime.getMemorySearchManager()` receives `agentId` in its parameters, allowing the binary to route requests to the correct database.

**BeU Mapping:**
- The binary receives `namespace` (agent ID) in every request
- Storage path: `{beu_data}/namespaces/{agent_id}/`

### Hermes

Hermes has **one agent identity** per running Hermes process (or per platform per user). The identity is defined by:
- `SOUL.md` (custom identity file)
- `DEFAULT_AGENT_IDENTITY` (built-in)

**BeU Mapping:**
- Use a single namespace for the Hermes instance: `default`

### Summary

| Host | Identity Boundary | Namespace Strategy |
|------|------------------|-------------------|
| OpenClaw | Per agent (`agentId`) | `{agentId}` |
| Hermes | Per Hermes instance (or per user/platform) | `default` |

---

## LLM Access (Compressor)

The binary needs LLM responses for the `distill` command (LLM-driven compression).

### How It Works

The adapter runs in the same process as the host - it CAN access the host's normalized LLM client. This is the correct pattern:

```
Adapter (in host process)
    │
    ├── Has access to host's LLM client (normalized transport, auth, routing)
    │
    │  distill request
    │  (includes prompt + context, adapter makes the LLM call)
    ▼
Binary (stateless)
    │
    │  receives LLM response
    │  parses output → extracts facts, invariants, wake pack
    ▼
Adapter stores results
```

**Benefits:**
- Reuses host's model routing, auth handling, transport normalization
- No need to configure separate API keys for BeU
- Adapter controls which model to use for distillation

### Implementation

The `distill` command payload includes:
- `prompt` - the compressor system prompt
- `context` - thread history, active invariants, prior wake pack
- `model` (optional) - which model to use

The adapter:
1. Makes the LLM call using host's client
2. Passes the raw response to the binary
3. Binary parses structured output (facts, invariants, etc.)

The binary's `compress/` module handles output parsing, not the LLM call itself.

---

## Embeddings

### Strategy: FTS5 + Native Vectors for Raw Turns

**Default: raw-turn hybrid search**
- SQLite FTS5 for full-text search over assistant/user/tool turn content (BM25 ranking)
- Native libsql vector columns for semantic similarity
- No external dependencies for storage/querying
- Works offline, on-device

**Where supported: vector enhancement**
- If host (OpenClaw) has embedding system, adapter can optionally use it
- Binary can accept pre-computed embeddings from adapter
- Search stays limited to raw turn content

### OpenClaw

OpenClaw has sophisticated embedding providers. The BeU adapter can:
1. Use binary's built-in FTS5 (default)
2. Optionally proxy to OpenClaw's embedding system for vector search
3. Configurable via adapter config

Built-in providers in OpenClaw: openai, gemini, voyage, mistral, ollama, local (sentence-transformers)

### Hermes

No built-in embedding system. Use binary's FTS5-only approach.

### Implementation

The binary's recall command works over raw assistant/user/tool turn content with FTS5. If embeddings are available (either from binary's own embedding module or passed in from adapter), vector scores are merged with BM25.
