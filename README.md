# BeU

BeU keeps agent orientation consistent across host integrations by enforcing the same two-step model everywhere:

1. capture state deltas through a `delta` tool
2. compact constraints through a `compress` tool when the constraint set reaches capacity
3. reconstruct current state from accumulated deltas and inject it into model context when a session starts

The canonical storage path is `~/.beu/state/deltas.jsonl`.

## Host Parity

| Host | Delta tool transport | State injection point |
| --- | --- | --- |
| Codex | MCP server | `SessionStart` hook installed into `~/.codex/hooks.json` |
| Copilot CLI | MCP server | `sessionStart` hook in `plugins/beu-copilot-cli/hooks.json` |
| OpenCode | Native custom tool | First `chat.message` in each session as the session-start equivalent |
| Hermes Agent | Native directory plugin | `pre_llm_call` injects the current state on the first turn |

All hosts share the same delta semantics, final state semantics, and prompt/tool wording through `src/beu-state.ts` and plugins/beu-hermes/shcemas.py.

## Canonical Files

- `agent-state.schema.json`: final reconstructed state shape
- `src/beu-state.ts`: shared delta validation, delta append, constraint compression, state folding, injected prompt text, and tool guidance
- `src/compute-agent-state.ts`: CLI that folds the delta log and prints injected context text
- `src/beu-mcp.ts`: MCP `delta` and `compress` tools used by Codex and Copilot CLI
- `plugins/beu-opencode/src/index.ts`: OpenCode-native wrapper around the shared state module with `delta` and `compress`
- `plugins/beu-hermes/plugin.yaml`, `plugins/beu-hermes/__init__.py`, `plugins/beu-hermes/schemas.py`, and `plugins/beu-hermes/tools.py`: Hermes Agent plugin

## Commands

From the repo root:

```bash
npm run build:mcp
npm run build:opencode
npm test
```

Install the MCP-backed artifacts into `~/.beu`:

```bash
npm run install:mcp
```

Install the OpenCode plugin bundle into `~/.config/opencode/plugins/beu-opencode.js`:

```bash
npm run install:opencode
```

## Host-Specific Install Notes

### Codex

- Codex uses the installed MCP server at `~/.beu/beu-mcp.js`.
- Codex needs a `SessionStart` hook that runs `~/.beu/compute-agent-state.js`.
- Install or refresh that hook with `node .agents/skills/beu-installer/scripts/install_hooks.js`.
- Codex hooks must be enabled in `~/.codex/config.toml`:

```toml
[features]
codex_hooks = true
```

### Copilot CLI

- Copilot CLI uses the installed MCP server at `~/.beu/beu-mcp.js`.
- `plugins/beu-copilot-cli/hooks.json` injects the output of `~/.beu/compute-agent-state.js` during `sessionStart`.

### OpenCode

- OpenCode does not expose a direct session-start hook.
- `plugins/beu-opencode/src/index.ts` injects computed state on the first `chat.message` in each session as the session-start equivalent.
- The shipped artifact is the single bundled file `dist/beu-opencode.js`.

### Hermes Agent

- Hermes Agent loads the repo root as a directory plugin via `plugins/beu-hermes/plugin.yaml` and `plugins/beu-hermes/__init__.py`.
- The plugin registers the BeU `delta` tool and injects reconstructed state on the first turn via `pre_llm_call`.
- Deltas are stored at `~/.beu/state/deltas.jsonl`, matching the other host integrations.

## Validation

Before finishing behavior changes, verify parity:

```bash
npm run build:mcp
npm run build:opencode
npm test
```
