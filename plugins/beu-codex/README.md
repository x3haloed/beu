# BeU MCP Plugin

BeU is a two-step state system:

1. expose a `delta` tool that records state changes
2. compute current state from accumulated deltas on session start and inject it into model context

The MCP server exposes one tool:

- `delta`
  - accepts a `state-delta.schema.json`-conformant object
  - appends the delta as one JSON line to `~/.beu/state/deltas.jsonl`

## Layout

- `.codex-plugin/plugin.json`
  - plugin manifest
  - points Codex at the local MCP server config

- `.mcp.json`
  - MCP launch config
  - starts `node ./beu-mcp.js` over stdio

- `beu-mcp.ts`
  - TypeScript source for the server
  - keeps the protocol, validation, and append logic in one place

- `compute-agent-state.ts`
  - TypeScript CLI that folds `~/.beu/state/deltas.jsonl` into the current agent state
  - prints plain JSON for hook-based context injection

- `beu-mcp.js`
  - checked-in runtime artifact for Node
  - same behavior as the TS source, without a build step

- `compute-agent-state.js`
  - built Node runtime for session-start hooks

## Behavior

The server:

1. Negotiates the MCP initialize handshake.
2. Advertises a single `delta` tool with the schema embedded in the server.
3. Validates each request locally.
4. Appends valid deltas to `~/.beu/state/deltas.jsonl` and returns the write path.

On session start, the installed hook runs `compute-agent-state.js`, which folds the accumulated deltas and returns the current state as developer-context text.

## Notes

The old durable-ledger hook surface is no longer the primary model. The current flow is delta capture plus session-start state reconstruction.
