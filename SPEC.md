# BeU Protocol Specification

Version: 1.0.0

All communication is JSON over STDIO. The host sends a request, BeU responds, and the process stays alive until stdin closes.

## Transport

- **Input**: Read newline-delimited JSON from stdin until EOF
- **Output**: Write JSON to stdout
- **Errors and diagnostics**: Write to stderr, non-zero exit code for process failure

Stderr may include structured tracing output when the host enables it. Hermes/OpenClaw adapters may map their own host-level logging env vars onto `BEU_*` before launch. Stdout remains reserved for protocol responses only.

## Request Format

```json
{
  "version": "1.0.0",
  "command": "distill|recall|rebuild|identity|index|status|wait_hold|wait_release",
  "id": "uuid",
  "namespace": "agent-123",       // Agent/namespace identifier
  "payload": { ... }
}
```

Note: `namespace` maps to the agent ID in OpenClaw or just "default" in Hermes, which has no multi-agent support. This provides multi-agent identity isolation.

## Response Format

```json
{
  "version": "1.0.0",
  "id": "uuid",
  "ok": true,
  "data": { ... }
}
```

```json
{
  "version": "1.0.0",
  "id": "uuid",
  "ok": false,
  "error": "error message",
  "code": "ERROR_CODE"
}
```

---

## Command: `wait_hold`

Hold a request open until a matching `wait_release` arrives.

### Request

```json
{
  "version": "1.0.0",
  "command": "wait_hold",
  "id": "req-hold",
  "payload": {
    "token": "release-me"
  }
}
```

### Response

The response is delayed until a matching `wait_release` command arrives for the same token.

---

## Command: `wait_release`

Release a blocked `wait_hold` request.

### Request

```json
{
  "version": "1.0.0",
  "command": "wait_release",
  "id": "req-release",
  "payload": {
    "token": "release-me"
  }
}
```

### Response

```json
{
  "version": "1.0.0",
  "id": "req-release",
  "ok": true,
  "data": {
    "message": "wait released",
    "token": "release-me"
  }
}
```

---

## Command: `distill`

Compress thread history into memory artifacts.

### Request

```json
{
  "version": "1.0.0",
  "command": "distill",
  "id": "req-123",
  "payload": {
    "namespace": "default",
    "thread_id": "thread-abc",
    "turn_id": "turn-xyz",
    "prior_wake_pack": {
      "content": "...",
      "summary": "..."
    },
    "active_invariants": [
      {
        "id": "inv-1",
        "claim": "User prefers verbose responses",
        "support_excerpt": "Multiple instances of user asking for detail",
        "falsifier": "Future turns show preference for brevity"
      }
    ],
    "thread_history": [
      {
        "entry_id": "turn:123:user",
        "kind": "user_turn",
        "content": "Write me a detailed explanation of X",
        "citation": "turn:123",
        "created_at": "2026-03-27T10:00:00Z"
      },
      {
        "entry_id": "turn:123:assistant",
        "kind": "agent_turn",
        "content": "Here is a detailed explanation...",
        "citation": "turn:123",
        "created_at": "2026-03-27T10:00:01Z"
      },
      {
        "entry_id": "event:456:tool_result",
        "kind": "tool_result",
        "content": "{\"result\": \"success\"}",
        "citation": "event:456",
        "created_at": "2026-03-27T10:00:02Z"
      }
    ]
  }
}
```

### Response

```json
{
  "version": "1.0.0",
  "id": "req-123",
  "ok": true,
  "data": {
    "wake_pack": {
      "content": "# Wake Pack\n\n- User asked: Write me a detailed explanation...",
      "summary": "User wants detailed technical explanations"
    },
    "facts": [
      {
        "id": "fact-1",
        "claim": "User prefers detailed technical explanations",
        "support_excerpt": "User asked for detailed explanation of X",
        "falsifier": "Future turns show preference for brief answers",
        "citations": ["turn:123:user"]
      }
    ],
    "invariant_adds": [
      {
        "id": "inv-new-1",
        "claim": "User prefers detailed technical explanations",
        "support_excerpt": "Multiple user requests for detailed content",
        "falsifier": "User starts asking for brief answers",
        "supersedes_ids": [],
        "derived_from_fact_ids": ["fact-1"]
      }
    ],
    "invariant_removes": [],
    "drift_flags": [],
    "drift_contradictions": [],
    "drift_merges": []
  }
}
```

---

## Command: `recall`

Search raw assistant/user/tool turn content.

### Request

```json
{
  "version": "1.0.0",
  "command": "recall",
  "id": "req-456",
  "payload": {
    "namespace": "default",
    "query": "what does user prefer",
    "limit": 5
  }
}
```

### Response

```json
{
  "version": "1.0.0",
  "id": "req-456",
  "ok": true,
  "data": {
    "hits": [
      {
        "source_type": "user_turn",
        "source_id": "turn-1",
        "content": "User prefers verbose responses",
        "score": 0.92,
        "citation": "turn-1"
      }
    ]
  }
}
```

---

## Command: `rebuild`

Rebuild entire memory from raw thread history.

### Request

```json
{
  "version": "1.0.0",
  "command": "rebuild",
  "id": "req-789",
  "payload": {
    "namespace": "default",
    "threads": [
      {
        "id": "thread-1",
        "turns": [
          {
            "id": "turn-1",
            "user_message": "Hello",
            "assistant_message": "Hi there",
            "created_at": "2026-03-27T10:00:00Z"
          }
        ]
      }
    ]
  }
}
```

### Response

```json
{
  "version": "1.0.0",
  "id": "req-789",
  "ok": true,
  "data": {
    "processed_turns": 15,
    "memory_snapshot": {
      "invariants_count": 3,
      "facts_count": 12,
      "wake_packs_count": 5,
      "drift_items_count": 0
    }
  }
}
```

---

## Command: `identity`

Query agent identity state.

### Request

```json
{
  "version": "1.0.0",
  "command": "identity",
  "id": "req-abc",
  "payload": {
    "namespace": "default",
    "query": "invariants|drift|summary|all",
    "limit": 10
  }
}
```

### Response

```json
{
  "version": "1.0.0",
  "id": "req-abc",
  "ok": true,
  "data": {
    "invariants": [
      {
        "id": "inv-1",
        "claim": "User prefers verbose responses",
        "support_excerpt": "Multiple user requests for detail",
        "falsifier": "User asks for brief answers",
        "status": "active"
      }
    ],
    "drift": {
      "flags": [],
      "contradictions": [],
      "merges": []
    },
    "summary": {
      "wake_pack": "Current: User preferences for detail...",
      "last_distilled": "2026-03-27T09:30:00Z"
    }
  }
}
```

---

## Command: `index`

Index raw assistant/user/tool turn content for future ledger search (chunked FTS + native libsql vectors).

### Request

```json
{
  "version": "1.0.0",
  "command": "index",
  "id": "req-index-1",
  "payload": {
    "namespace": "default",
    "entries": [
      {
        "entry_id": "turn:123:user",
        "source_type": "ledger_entry",
        "source_id": "turn:123",
        "content": "Write me a detailed explanation of X",
        "metadata": {
          "kind": "user_turn",
          "thread_id": "thread-1",
          "turn_id": "turn-123"
        }
      }
    ],
    "embed": true
  }
}
```

### Response

```json
{
  "version": "1.0.0",
  "id": "req-index-1",
  "ok": true,
  "data": {
    "indexed": 1,
    "embeddings_generated": 1
  }
}
```

---

## Command: `status`

Check the memory plugin status (embedding availability, storage health).

### Request

```json
{
  "version": "1.0.0",
  "command": "status",
  "id": "req-status-1",
  "payload": {
    "namespace": "default"
  }
}
```

### Response

```json
{
  "version": "1.0.0",
  "id": "req-status-1",
  "ok": true,
  "data": {
    "storage": "ok",
    "embedding_available": true,
    "vector_available": true,
    "last_distilled": "2026-03-27T10:00:00Z",
    "counts": {
      "invariants": 5,
      "facts": 23,
      "wake_packs": 12,
      "drift_items": 2
    }
  }
}
```

---

## Error Codes

| Code | Description |
|------|-------------|
| `INVALID_REQUEST` | Malformed JSON or missing required fields |
| `UNKNOWN_COMMAND` | Command not recognized |
| `STORAGE_ERROR` | Database or filesystem error |
| `MODEL_ERROR` | LLM call failed |
| `NOT_FOUND` | Requested resource doesn't exist |
| `NAMESPACE_CONFLICT` | Namespace already exists |

## Versioning

- `version` field is required in all requests/responses
- Clients should specify the protocol version they expect
- Server responds with the same version (or closest compatible)
- Backward compatibility: newer server works with older clients
