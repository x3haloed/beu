# BeU

BeU keeps agent orientation consistent across three host integrations by enforcing the same two-step model everywhere:

1. capture state deltas through a `delta` tool
2. reconstruct current state from accumulated deltas and inject it into model context when a session starts

The canonical storage path is `~/.beu/state/deltas.jsonl`.

## Host Parity

| Host | Delta tool transport | State injection point |
| --- | --- | --- |
| Codex | MCP server | `SessionStart` hook installed into `~/.codex/hooks.json` |
| Copilot CLI | MCP server | `sessionStart` hook in `plugins/beu-copilot-cli/hooks.json` |
| OpenCode | Native custom tool | First `chat.message` in each session as the session-start equivalent |

All three hosts share the same delta semantics, final state semantics, and prompt/tool wording through `src/beu-state.ts`.

## Canonical Files

- `agent-state.schema.json`: final reconstructed state shape
- `src/beu-state.ts`: shared delta validation, delta append, state folding, injected prompt text, and `delta` tool guidance
- `src/compute-agent-state.ts`: CLI that folds the delta log and prints injected context text
- `src/beu-mcp.ts`: MCP `delta` tool used by Codex and Copilot CLI
- `plugins/beu-opencode/src/index.ts`: OpenCode-native wrapper around the shared state module

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

## Validation

Before finishing behavior changes, verify parity:

```bash
npm run build:mcp
npm run build:opencode
npm test
```