# BeU Repository Layout

```
beu/
├── ARCHITECTURE.md          # Detailed system design (host requirements, data flows)
├── REPO_LAYOUT.md           # This file
├── README.md                # Quick start, installation
├── SPEC.md                  # STDIO protocol specification
│
├── bin/                     # Built binaries (gitignored)
│   └── beu                  # Final executable
│
├── src/                     # Rust source (stateless binary)
│   ├── main.rs              # Entry point, CLI dispatcher, STDIO loop
│   ├── lib.rs               # Library root
│   │
│   ├── commands/            # Command implementations
│   │   ├── mod.rs
│   │   ├── distill.rs       # Compression/distillation (LLM-driven)
│   │   ├── recall.rs        # Memory search (hybrid: FTS + vectors)
│   │   ├── index.rs         # Index content for recall
│   │   ├── rebuild.rs       # Full rebuild from raw history
│   │   ├── identity.rs      # Agent identity queries
│   │   └── status.rs        # Plugin status check
│   │
│   ├── storage/             # Persistence layer
│   │   ├── mod.rs
│   │   ├── db.rs            # SQLite operations (libsql)
│   │   ├── fact.rs          # Fact storage
│   │   ├── invariant.rs     # Invariant storage
│   │   ├── drift.rs         # Drift item storage
│   │   ├── wakepack.rs      # Wake pack storage
│   │   ├── recall.rs        # Recall chunk storage
│   │   └── migrations/      # Schema migrations
│   │
│   ├── embedding/           # Embedding/vector operations
│   │   ├── mod.rs
│   │   ├── provider.rs     # Embedding provider abstraction
│   │   ├── openai.rs       # OpenAI embeddings
│   │   ├── ollama.rs        # Ollama embeddings
│   │   └── local.rs        # Local/sentence-transformers
│   │
│   ├── compress/            # LLM-driven compression
│   │   ├── mod.rs
│   │   ├── client.rs       # LLM client abstraction
│   │   ├── prompts.rs      # Compressor system prompts
│   │   └── output.rs       # Compressor output parsing
│   │
│   ├── protocol/            # STDIO protocol
│   │   ├── mod.rs
│   │   ├── request.rs       # Request parsing
│   │   ├── response.rs      # Response serialization
│   │   └── error.rs         # Error codes
│   │
│   └── types/               # Shared types
│       ├── mod.rs
│       ├── fact.rs
│       ├── invariant.rs
│       ├── drift.rs
│       ├── wakepack.rs
│       └── ledger.rs
│
├── tests/                   # Integration tests
│   ├── commands.rs
│   ├── protocol.rs
│   └── storage.rs
│
├── Cargo.toml              # Rust manifest
├── rustfmt.toml            # Formatting config
└── .cargo/                 # Build config
    └── config.toml
```

## Notes

- **Adapters are separate repos** - `beu-hermes` (Python) and `beu-openclaw` (TypeScript) are their own repos. They wrap this binary and implement the host plugin API.

- **Core is stateless** - The binary has no memory between calls. All state lives in `storage/`.

- **Storage is pluggable** - Default is SQLite (libsql), but the `storage/` abstraction allows swapping backends.

- **Embedding providers** - The `embedding/` module supports multiple providers (OpenAI, Ollama, local). Configured at runtime.

- **Compressor** - The `compress/` module handles LLM-driven distillation. Currently uses OpenAI-compatible API, extensible to others.