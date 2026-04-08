# BeU Codex Plugin

Codex uses the shared BeU MCP server for the `delta` tool and a Codex `SessionStart` hook for state injection.

The canonical architecture, shared files, and validation commands are documented in the repo root [README](../../README.md).

## Codex-Specific Pieces

- `.codex-plugin/plugin.json`: Codex plugin manifest
- `.mcp.json`: launches `node ./beu-mcp.js` over stdio
- `beu-mcp.js`: installed MCP runtime copied to `~/.beu/beu-mcp.js`

## Install Notes

1. Build and install the MCP artifacts with `npm run install:mcp` from the repo root.
2. Install or refresh the Codex `SessionStart` hook with `node .agents/skills/beu-installer/scripts/install_hooks.js`.
3. Ensure `~/.codex/config.toml` contains `codex_hooks = true` under `[features]`.

That hook runs `~/.beu/compute-agent-state.js`, reads `~/.beu/state/deltas.jsonl`, and injects the reconstructed state as plain text context.
