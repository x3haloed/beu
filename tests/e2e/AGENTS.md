# BeU E2E Tests

End-to-end tests for the BeU protocol and any future host-facing adapters.

## Scope

- Keep these tests aligned with `SPEC.md`.
- Prefer local, deterministic fixtures over network dependencies.
- Use real protocol requests where possible so the suite exercises the STDIO contract instead of implementation details.

## Setup

```bash
cd tests/e2e

# Create virtualenv (one-time)
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -e .

# Install browser binaries if the suite uses a browser fixture
playwright install chromium
```

Dependencies should stay minimal. Add only the tools the suite actually needs.

## Running Tests

```bash
# Activate venv first
source .venv/bin/activate

# Run all scenarios
pytest scenarios/

# Run a specific scenario
pytest scenarios/test_my_feature.py

# Run with verbose output
pytest scenarios/ -v

# Run with a specific timeout
pytest scenarios/ --timeout=60

# Run with a headed browser, if applicable
HEADED=1 pytest scenarios/
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

## Writing New Scenarios

1. Create `scenarios/test_my_feature.py`.
2. Use the narrowest fixture that exercises the behavior.
3. Keep assertions focused on observable protocol output.
4. Add regression coverage for any bug fix.

## Gotchas

- Do not add browser tooling unless a scenario genuinely needs it.
- Keep the suite local-first and deterministic.
- If a test depends on an optional backend or service, document that dependency clearly in the scenario file and here.
