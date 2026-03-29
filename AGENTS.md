# BeU Development Guide

Keep these always in view when working on the repo as guiding principles:
- Docker is unacceptable *except* as a light dockerfile shim around the system. It's an afterthought -- not a first-class assumption
- BeU should keep an extremely light footprint on the host
- BeU should keep a lightweight footprint on dependency expectations
  - Example: Prefer local file stores over installed database solutions
  - Prefer local processing over hosted processing. Example: vector search is better at semantic search than FTS5, but FTS5 must be made to work as well as possible *first* before exploring vector search, because it can be done on-device. The LLM calls themselves are somewhat of an exception, because BeU plugs into frameworks that already direct that for us.
- Invariants are strictly: what stays the same when everything else changes in a given context
- LLMs like sneaking policy, preferences, and narration into statements of invariance when asked to distill invariants from context. We have to fight that every step of the way.

## Build & Test

```bash
cargo fmt                                                       # format
cargo clippy --all --benches --tests --examples --all-features  # lint (zero warnings)
cargo test                                                      # unit tests
cargo test --features integration                               # + libsql tests
RUST_LOG=beu=debug cargo run                                    # run with logging
```

E2E tests: see `tests/e2e/AGENTS.md`.

## Code Style

- Prefer `crate::` for cross-module imports; `super::` is fine in tests and intra-module refs
- No `pub use` re-exports unless exposing to downstream consumers
- No `.unwrap()` or `.expect()` in production code (tests are fine)
- Use `thiserror` for error types in `error.rs`
- Map errors with context: `.map_err(|e| SomeError::Variant { reason: e.to_string() })?`
- Prefer strong types over strings (enums, newtypes)
- Keep functions focused, extract helpers when logic is reused
- Comments for non-obvious logic only

## Parity and Testing

- If you change implementation any harness adapter, make sure you update all the others or at least flag it for the user.
- Add the narrowest tests that validate the change: unit tests for local logic, integration tests for runtime/DB/routing behavior, and E2E or trace coverage for gateway, approvals, extensions, or other user-visible flows.


## Architecture

Prefer generic/extensible architectures over hardcoding specific integrations. Ask clarifying questions about the desired abstraction level before implementing.

Key extensibility points in BeU: `Db`, `Ledger`, `Protocol`, `Message`, `Event`, `Turn`, `Thread`.

All I/O is async with tokio. Use `Arc<T>` for shared state, `RwLock` for concurrent access.

## Protocol And Storage

The binary speaks JSON over STDIO and follows `SPEC.md`. Keep request/response shapes and command names aligned with the spec.

Storage logic lives in `src/storage/`. Keep libsql-specific code there unless a caller is part of the storage boundary itself.

## Project Structure

```text
src/
├── lib.rs              # Library root, module declarations
├── protocol/           # STDIO JSON request/response handling
├── storage/            # libsql-backed persistence
└── types/              # Shared request/response and domain types

tests/
├── *.rs                # Rust unit/integration tests for storage/protocol behavior
└── e2e/                # End-to-end tests and harness docs
    └── *.rs            # Rust e2e adapter tests with isolated temp homes/venvs
```

## Module Specs

When modifying a module with a spec, read the spec first. Code follows spec; spec is the tiebreaker.

**Module-owned initialization:** Module-specific initialization logic must live in the owning module as a public factory function or constructor. Entry-point code should orchestrate calls, not embed setup detail.

| Module | Spec |
|--------|------|
| `src/protocol/` | `SPEC.md` |
| `tests/e2e/` | `tests/e2e/AGENTS.md` |

## Debugging

```bash
RUST_LOG=beu=trace cargo run  # verbose
RUST_LOG=beu=debug cargo run  # debug logging
```
