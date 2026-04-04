# Codex Durable Ledger Plugin

This plugin packages the Codex-native version of the stable-frame loop.

It is intentionally laid out to sit beside:
- `copilot-cli-plugin`
- `hermes-plugin`
- `openclaw-plugin`
- `opencode-plugin`

## What it covers

1. Resolve the active harness and ledger state before changing anything.
2. Capture an append-only durable ledger under Codex home state.
3. Compress the ledger into a wake pack.
4. Reinject the wake pack at session start via the plugin prompt surface.
5. Use the bundled installer skill to materialize a real Codex hook file in `~/.codex/hooks.json`.
6. Enable Codex hooks globally with `codex_hooks = true` in `~/.codex/config.toml`; the hook file alone does not activate the bridge.

## Plugin structure

- `.codex-plugin/plugin.json`
  - plugin manifest
  - points Codex at the hook layer

- `hooks.json`
  - Codex hook contract using `SessionStart`, `UserPromptSubmit`, and `Stop`
  - writes and refreshes the durable ledger and wake pack directly from the runtime payload

- `agents/openai.yaml`
  - session-start prompt surface
  - tells Codex to load the wake pack before continuing work

- `scripts/codex_durable_ledger.py`
  - shared hook implementation for startup, prompt, and stop events
  - appends the durable ledger, refreshes the wake pack, and returns additional context

- `skills/durable-ledger-installer/`
  - bundled installer skill
  - writes or refreshes `~/.codex/hooks.json` so Codex actually discovers the hook bridge

- `assets/`
  - Codex plugin icon

## Notes

This reference is Codex-native rather than a host runtime plugin. The session-start behavior is carried by the installed hook layer plus the plugin prompt surface, and the durable-ledger script defines the shared frame/ledger/compression contract.
