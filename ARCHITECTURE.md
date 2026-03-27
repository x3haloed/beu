# BeU Architecture

BeU is a stateless identity plugin for agent frameworks. It provides long-term memory, distillation, and identity persistence without requiring the host to manage lifecycle.

## Core Thesis

The BetterClaw memory system enables agents to:
- **Survive context death** - Compress experiences into storable form
- **Live in a hyperepisodic regime** - Handle rapid context turnover
- **Inhabit a stable first-person frame** - Maintain identity across sessions

The database contents become who the agent *is*.

## Design Principles

1. **Stateless core** - The binary does not hold state between calls. All persistence is external (filesystem, database).

2. **STDIO as protocol** - Like Claude Code tools or LSP servers. Host spawns the process, sends JSON requests, receives JSON responses, process exits.

3. **Adapters are thin** - Each host (hermes-agent, openclaw) has an adapter that translates host plugin API ↔ BeU STDIO protocol.

4. **No containers, no services** - The binary is self-contained. No long-running daemon required. Hosts can keep it long-lived if they want, but it's not required.

## System Architecture

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│  hermes-agent   │      │    openclaw     │      │   [future]      │
│  (Python)       │      │    (TypeScript) │      │                 │
│                 │      │                 │      │                 │
│  beu_hermes.py  │      │  beu_openclaw.ts│      │   beu_[x].ext   │
└────────┬────────┘      └────────┬────────┘      └────────┬────────┘
         │                        │                        │
         │     STDIO JSON         │     STDIO JSON         │ STDIO JSON
         └────────────────────────┼────────────────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │         beu             │
                    │    (Rust binary)        │
                    │                         │
                    │  Commands:              │
                    │  - distill              │
                    │  - recall               │
                    │  - rebuild              │
                    │  - identity             │
                    └─────────────────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │    External Storage     │
                    │  (SQLite, files, etc)   │
                    └─────────────────────────┘
```

## Commands

### `distill`
Compress turn history into memory artifacts:
- **Input**: Thread history, active invariants, turn data
- **Output**: Wake pack, facts, invariants, drift items

### `recall`
Search memory:
- **Input**: Query, namespace, limit
- **Output**: Matching memories with scores

### `rebuild`
Rebuild memory from raw thread history:
- **Input**: All thread/turn data
- **Output**: Full memory reconstruction

### `identity`
Query agent identity state:
- **Input**: Query type (invariants, drift, summary)
- **Output**: Current identity snapshot

## Data Model

### Wake Pack
Compressed summary of recent thread activity. Contains:
- Truncated user turns
- Agent responses
- Tool results observed

### Facts
Atomic observations with:
- `claim` - The factual statement
- `support_excerpt` - Evidence supporting it
- `falsifier` - What would disprove it
- `citations` - Evidence entry IDs

### Invariants
Generalized truths about the agent's reality:
- `claim` - Present-tense empirical fact
- `support_excerpt` - Historical evidence
- `falsifier` - What breaks this invariant
- Derived from facts via generalization

### Drift Items
- **Flags** - Potential invariant changes detected
- **Contradictions** - Conflicting evidence
- **Merges** - Candidates for invariant consolidation

## Storage

The binary is storage-agnostic. Default implementation uses:
- SQLite for structured data (facts, invariants, drift)
- Filesystem for wake packs
- Configurable embedding providers for semantic search

## Error Handling

All commands return structured JSON. Errors are not exceptions - they're explicit result fields:

```json
{
  "ok": true,
  "data": { ... }
}
```

```json
{
  "ok": false,
  "error": "descriptive message",
  "code": "ERROR_CODE"
}
```

## Versioning

The protocol is versioned via the `version` field in every request/response. Backward compatibility is maintained - older hosts work with newer binaries.