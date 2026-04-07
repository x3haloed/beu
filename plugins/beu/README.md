# BeU MCP Plugin

BeU exposes one tool:

- `delta`
  - accepts a `state-delta.schema.json`-conformant object
  - appends the delta as one JSON line to `~/.codex/state/deltas.jsonl`

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

- `beu-mcp.js`
  - checked-in runtime artifact for Node
  - same behavior as the TS source, without a build step

## Behavior

The server:

1. Negotiates the MCP initialize handshake.
2. Advertises a single `delta` tool with the schema embedded in the server.
3. Validates each request locally.
4. Appends valid deltas to `~/.codex/state/deltas.jsonl` and returns the write path.

## Notes

The old durable-ledger hook surface is no longer part of this plugin manifest. The repo can keep the older files around, but Codex now loads only the MCP server defined by `.mcp.json`.
