# BeU OpenCode Plugin

BeU for OpenCode follows the same two-step pattern as the other plugins in this repo:

1. expose a `delta` tool that appends validated state deltas to `~/.beu/state/deltas.jsonl`
2. inject the computed current state into model context when a session begins

OpenCode does not expose a direct session-start prompt hook like Codex or Copilot. This plugin uses the same practical pattern as `opencode-supermemory`: it injects the computed state on the first user message seen in each session via `chat.message`.

## Install

### Local plugin

Copy or symlink this folder into one of:

- `~/.config/opencode/plugins/beu-opencode`
- `.opencode/plugins/beu-opencode`

### NPM config

If published as a package, add it to your OpenCode config:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["beu-opencode"]
}
```

## Behavior

- Adds a native `delta` tool directly through OpenCode's plugin API.
- Stores deltas in `~/.beu/state/deltas.jsonl`.
- On the first message in a session, computes the current state from the accumulated deltas and injects it as synthetic context.

## Tool

The `delta` tool accepts the same fields as the MCP-backed variants:

- `set_focus`
- `add_threads`
- `remove_threads`
- `add_constraints`
- `add_recent`
- `set_next`

It returns a plain string confirming the write path.