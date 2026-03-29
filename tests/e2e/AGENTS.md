# BeU E2E Tests

End-to-end tests for the BeU protocol and host-facing adapters.
Keep them local-first, isolated, and deterministic.

## Scope

- Keep these tests aligned with `SPEC.md`.
- Prefer local, deterministic fixtures over network dependencies.
- Use real protocol requests where possible so the suite exercises the STDIO contract instead of implementation details.

## Running Tests

```bash
# Run Rust e2e tests from the repo root when present
cargo test --test hermes_adapter_integration -- --nocapture
```

## Test Scenarios

Document each scenario with the behavior it covers, the protocol command it exercises, and any external service it relies on.

## Shared Helpers

Keep shared constants and fixtures in one place. Import selectors, protocol constants, and common helper functions instead of hardcoding them inline.

## Fixtures

- Keep expensive setup session-scoped where possible.
- Keep browser state clean per test when UI coverage needs isolation.
- Fail loudly when prerequisites are missing; prefer explicit gating over silent skipping.

## Protocol Tests

- Use `httpx.AsyncClient` for direct HTTP calls when an adapter exposes HTTP.
- Use `aiohttp` or the lightest available async client for SSE only when the scenario needs streaming.
- Use the commands from `SPEC.md`: `distill`, `recall`, `rebuild`, `identity`, `index`, and `status`.
- For Rust e2e adapter tests, use isolated temp homes/venvs and real subprocess execution. Keep dependency installs contained to the test fixture.
- For adapter coverage against Hermes or OpenClaw, discover the local host repo from `BEU_HERMES_AGENT_REPO` or `BEU_OPENCLAW_REPO` first, then fall back to nearby checkout discovery. Do not hard-code machine-specific paths.

## Writing New Scenarios

1. add `tests/e2e/*.rs` tests that exercise the real host/plugin boundary.

## Gotchas

- Do not add browser tooling unless a scenario genuinely needs it.
- Keep the suite local-first and deterministic.
- If a test depends on an optional backend or service, document that dependency clearly in the scenario file and here.
