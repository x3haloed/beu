# BeU OpenCode Plugin

OpenCode follows the same two-step BeU model as Codex and Copilot, but uses a native custom tool and a first-message injection path instead of MCP plus a real session-start hook.

The canonical architecture, shared files, and validation commands are documented in the repo root [README](../../README.md).

OpenCode does not expose a direct session-start prompt hook like Codex or Copilot. This plugin injects the computed state on the first user message seen in each session via `chat.message`, which is the OpenCode session-start equivalent.

## Install

### Local plugin

From the repo root, build and install the single-file plugin artifact:

```bash
npm run install:opencode
```

That copies `dist/beu-opencode.js` into `~/.config/opencode/plugins/beu-opencode.js`.

### NPM config

If published as a package, add it to your OpenCode config:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["beu-opencode"]
}
```

## Behavior

- Adds native `delta` and `compress` tools directly through OpenCode's plugin API.
- Stores deltas in `~/.beu/state/deltas.jsonl`.
- On the first message in a session, computes the current state from the accumulated deltas and injects it as synthetic context.
- The installed OpenCode artifact is a single bundled file in `dist/beu-opencode.js`.

## Tool

The `delta` tool accepts the same fields as the MCP-backed variants:

- `set_focus`
- `add_threads`
- `remove_threads`
- `add_constraints`
- `add_recent`
- `set_next`

The `compress` tool accepts one field:

- `constraint`

It returns a plain string confirming the write path.
