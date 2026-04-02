# Durable Ledger OpenCode Plugin

This reference is a single-file OpenCode plugin that can be auto-discovered from the local plugin directory.

## Install

Copy [durable-ledger.ts](./durable-ledger.ts) into one of these directories as a single file:

- Project: `.opencode/plugins/durable-ledger.ts`
- Global: `~/.config/opencode/plugins/durable-ledger.ts`

Do not copy this entire reference directory into `.opencode/plugins/`. OpenCode auto-discovers `.ts` and `.js` files in that directory, so the plugin artifact must stay a single file.

## Behavior

- Uses the documented OpenCode `event` hook.
- Handles `session.created`, `message.updated`, `session.updated`, `session.idle`, `session.compacted`, `session.error`, and `tool.execute.after`.
- Writes append-only JSONL ledger files under `~/.config/opencode/state/durable-ledger` by default.
- Honors `DURABLE_LEDGER_STORAGE_ROOT` to override the ledger root.
- Honors `DURABLE_LEDGER_NAMESPACE` to force a stable namespace instead of using the session id.

## Output Layout

The plugin writes under:

```text
<storage-root>/v1/namespaces/<namespace>/
```

The namespace directory contains:

- `workspaces.jsonl`
- `agents.jsonl`
- `threads.jsonl`
- `turns.jsonl`
- `events.jsonl`
- `distill_state.jsonl`
- `ledger_entries.jsonl`
- `ledger_entry_chunks.jsonl`

`session.created` creates the namespace directory and the table files immediately, so a working install produces visible ledger artifacts before the first assistant response.