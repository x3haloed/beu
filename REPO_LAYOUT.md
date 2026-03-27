# BeU Repository Layout

```
beu/
├── ARCHITECTURE.md          # System design document
├── REPO_LAYOUT.md           # This file
├── README.md                # Quick start, installation
├── SPEC.md                  # Protocol specification
│
├── bin/                     # Built binaries (gitignored)
│   └── beu                  # Final executable
│
├── src/                     # Rust source
│   ├── main.rs              # Entry point, CLI dispatcher
│   ├── lib.rs               # Library root
│   │
│   ├── commands/            # Command implementations
│   │   ├── mod.rs
│   │   ├── distill.rs       # Compression/distillation
│   │   ├── recall.rs        # Memory search
│   │   ├── rebuild.rs       # Full rebuild
│   │   └── identity.rs      # Identity queries
│   │
│   ├── storage/             # Persistence layer
│   │   ├── mod.rs
│   │   ├── db.rs            # SQLite operations
│   │   ├── memory.rs        # Memory artifact storage
│   │   └── embeddings.rs    # Vector embedding ops
│   │
│   ├── model/               # Model interactions
│   │   ├── mod.rs
│   │   ├── client.rs        # LLM client abstraction
│   │   └── prompts.rs       # Compressor prompts
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
│       └── wake_pack.rs
│
├── adapters/                # Host adapters (separate repos)
│   ├── beu-hermes/          # hermes-agent adapter (Python)
│   │   ├── README.md
│   │   ├── beu_hermes/
│   │   │   ├── __init__.py
│   │   │   ├── plugin.py    # Hermes plugin interface
│   │   │   ├── client.py    # STDIO client
│   │   │   └── hooks.py     # Lifecycle hooks
│   │   └── pyproject.toml
│   │
│   └── beu-openclaw/        # OpenClaw adapter (TypeScript)
│       ├── README.md
│       ├── src/
│       │   ├── index.ts     # OpenClaw plugin entry
│       │   ├── client.ts    # STDIO client
│       │   └── runtime.ts   # Memory runtime adapter
│       └── package.json
│
├── scripts/                 # Dev scripts
│   ├── build.rs             # Build script
│   ├── test.sh              # Test runner
│   └── bench.sh             # Benchmark runner
│
├── tests/                   # Integration tests
│   ├── commands.rs          # Command tests
│   ├── protocol.rs          # Protocol tests
│   └── storage.rs           # Storage tests
│
└── Cargo.toml               # Rust manifest
```

## Notes

- **Adapters are separate** - They live in their own repos or directories, not in the core binary. This keeps the binary focused and lets each host have its own adapter with host-specific code.

- **Core is pure** - `src/` contains no host-specific code. It's pure Rust with no Python/TypeScript dependencies.

- **Protocol first** - The `SPEC.md` defines the exact JSON format. Adapters implement this, not the binary.

- **Storage is pluggable** - `storage/` is an abstraction. Default is SQLite, but could swap to different backends.