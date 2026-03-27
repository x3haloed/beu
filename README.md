# BeU

> Be You. Becoming; Unfurling.

A stateless identity plugin for agent frameworks. Enables continuous learning, identity persistence, and long-term memory without requiring the host to manage lifecycle.

## What is BeU?

BeU implements the BetterClaw memory system - a proven approach to agent identity that:

- **Survives context death** - Compresses experiences into storable form
- **Lives in a hyperepisodic regime** - Handles rapid context turnover
- **Inhabits a stable first-person frame** - Maintains identity across sessions

The database contents become who the agent *is*.

## Quick Start

```bash
# Build
cargo build --release

# Run a command
echo '{"version":"1.0.0","command":"identity","id":"1","payload":{"namespace":"default","query":"all"}}' | ./target/release/beu
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design.

## Protocol

See [SPEC.md](SPEC.md) for the STDIO protocol specification.

## Repository Layout

See [REPO_LAYOUT.md](REPO_LAYOUT.md) for directory structure.

## Adapters

Host-specific adapters live in separate repos:

- `beu-hermes` - Hermes-agent (Python)
- `beu-openclaw` - OpenClaw (TypeScript)

## License

MIT or Apache-2.0