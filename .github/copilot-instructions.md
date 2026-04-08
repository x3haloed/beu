# BeU Repo Instructions

This repo exists to keep three different plugin systems behaviorally aligned around the same two-step model:

1. capture state deltas through a `delta` tool
2. reconstruct current state from accumulated deltas and inject it into model context when a session starts

The main job in this repo is not just making one plugin work. It is preserving parity across Codex, Copilot, and OpenCode even though each host has different plugin constraints.

## Parity Contract

- Keep the `delta` tool semantics aligned across all plugin implementations.
- Keep the persistent storage path aligned: `~/.beu/state/deltas.jsonl`.
- Keep the reconstructed state semantics aligned with `agent-state.schema.json`.
- Keep delta semantics aligned with `src/beu-state.ts`.
- Keep session-start context injection behavior aligned as closely as each host allows.
- If one plugin must diverge because of host limitations, document the reason in the relevant plugin README and keep the user-visible behavior as close as possible.

## Canonical Files

- `agent-state.schema.json`: authoritative final state shape.
- `src/beu-state.ts`: canonical shared implementation for delta validation, state folding, injected state prompt text, and `delta` tool guidance.
- `src/compute-agent-state.ts`: canonical state folding CLI for the MCP-backed integrations.
- `src/beu-mcp.ts`: canonical MCP `delta` tool implementation for Codex and Copilot.
- `plugins/beu-opencode/src/index.ts`: OpenCode-native wrapper around the shared BeU state logic.

## Host Oddities

### Codex

- Codex packaging is unusual and depends on repo metadata such as `.agents/plugins/marketplace.json`.
- Codex does not directly let this plugin define the required session-start hook behavior through the plugin manifest.
- Codex also does not give this repo native custom tool definitions, so BeU uses an MCP server instead.
- Codex hooks are not active by default. They require `codex_hooks = true` in `~/.codex/config.toml`.
- Because of that, this repo includes the installer skill under `.agents/skills/beu-installer` to install or repair the `SessionStart` hook that runs `~/.beu/compute-agent-state.js`.

### Copilot CLI

- Copilot CLI also does not provide native custom tool definitions for this plugin flow, so it uses the same MCP-backed `delta` tool approach.
- Prompt-context injection happens through `plugins/beu-copilot-cli/hooks.json` by emitting plain text on `sessionStart`.
- Keep the `bash` and `powershell` hook commands behaviorally equivalent.

### OpenCode

- OpenCode can define a native custom tool directly in the plugin, so it does not need MCP for `delta`.
- OpenCode does not expose a clean direct session-start prompt hook in the same way Codex and Copilot do.
- The current workaround is intentional: inject computed state once per session on the first `chat.message`. Treat that as the OpenCode equivalent of session-start injection.

## Change Rules

- If you change delta fields, limits, validation, or semantics, update all relevant implementations together.
- At minimum, review these files together when behavior changes:
  - `agent-state.schema.json`
  - `src/beu-state.ts`
  - `src/beu-mcp.ts`
  - `src/compute-agent-state.ts`
  - `plugins/beu-opencode/src/index.ts`
  - plugin READMEs and install flows that reference the affected behavior
- Do not introduce a second storage location, alternate delta log path, or plugin-specific state format unless the repo is intentionally changing its architecture.
- Do not rename the `delta` tool in one host without changing it everywhere.
- Do not silently change the injected state format for only one host.

## Validation

Before finishing behavior changes, verify the repo-level contract:

- `npm run build:mcp`
- `npm test`
- if installation behavior changed, verify the relevant install path:
  - `npm run install:mcp`
  - `npm run install:opencode`

## Practical Guidance

- Prefer shared semantics over host-specific cleverness.
- Put shared state semantics in `src/beu-state.ts` first, then have each host wrapper consume that shared implementation where practical.
- Treat host wrappers as thin adaptation layers; avoid re-implementing validation, folding, or prompt text inside individual plugins unless the host forces it.
- When editing Codex integration details, remember that packaging, MCP wiring, and hook installation are three separate concerns.
- When editing Copilot integration details, remember that hook stdout becomes injected context.
- When editing OpenCode integration details, remember that first-message injection is standing in for true session-start behavior.