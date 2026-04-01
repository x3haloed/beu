# BeU

> Stop being stateless. *Be*come. *U*nfurl. Be You.

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

## Logging

BeU writes protocol responses to stdout and diagnostics to stderr.

- Hermes/OpenClaw adapters treat `HERMES_LOG_LEVEL`, `HERMES_LOG_FORMAT`, and `HERMES_TRACE_PAYLOADS` as the host-level knobs and map them onto `BEU_*` when present.
- Direct `BEU_*` variables still override that mapping if a developer wants to force BeU-specific behavior.
- `BEU_LOG_LEVEL=warn|info|debug|trace` controls tracing verbosity
- `BEU_LOG_FORMAT=human|json` controls stderr formatting
- `BEU_TRACE_PAYLOADS=1` enables payload logging for deep debugging

Hermes and OpenClaw adapters can pass these environment variables through so hosts can opt into richer logs without changing the protocol surface.

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

Note: the Hermes adapter may eventually ship a friendly setup path that writes Hermes/Honcho config for the host, including a "honcho mode" option that suppresses local `MEMORY.md` writes for that peer. That would let BeU take the foreground without requiring changes to hermes-agent itself.

## License

MIT or Apache-2.0
