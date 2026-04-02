# Copilot CLI Durable Ledger Plugin

This plugin installs into GitHub Copilot CLI and uses hooks to write an append-only JSONL durable ledger.

## Install

Use the plugin command, not the top-level install command:

```text
copilot plugin install /Users/chad/Repos/beu/durable-ledger/references/copilot-cli-plugin
```

Notes:
- On this machine, `copilot plugin install --help` does not list local filesystem paths, but the command accepts an absolute local path and installs successfully.
- Prefer an absolute path when testing local installs.
- After editing the plugin locally, reinstall it. Copilot CLI runs the cached installed copy, not your source checkout.

## Path Resolution

Do not hardcode your source checkout path in `hooks.json`.

The hooks in this plugin resolve the installed plugin root at runtime by:
- checking `COPILOT_CONFIG_DIR` if it is set
- otherwise falling back to `~/.copilot/installed-plugins`
- scanning installed `plugin.json` files for `"name": "durable-ledger"`

That keeps the hook commands portable across machines and avoids baking a personal home-directory checkout path into the plugin.

## Configure Storage

This plugin now works in a standard Copilot CLI session without launch-time env vars.

Default behavior:
- use the fixed per-user root `~/.copilot/state/durable-ledger`
- derive the namespace from a stable workspace root, not from a transient hook working directory
- resolve the workspace root by walking upward from the hook payload `cwd` until it finds a common project marker such as `.git`, `pyproject.toml`, `package.json`, `Cargo.toml`, or `go.mod`
- if no project marker is found, fall back to the hook payload `cwd`

That means the normal path is simple: install the plugin once, start Copilot normally, and the plugin will create and reuse:

```text
~/.copilot/state/durable-ledger/v1/namespaces/<workspace-namespace>/
```

If you want to pin a different namespace or storage location without changing how Copilot is launched, create:

```text
~/.copilot/durable-ledger.json
```

Example:

```json
{
	"namespace": "agentic-workspace",
	"storageRoot": "state/durable-ledger"
}
```

`storageRoot` may be absolute or relative to `~/.copilot`.

Environment variables still work as optional overrides, but they are no longer required for ordinary use.

## Existing Install Evidence

Look in these places first when deciding whether a durable ledger is already installed and active:

- `copilot plugin list`
- `~/.copilot/installed-plugins/` for the installed plugin cache
- `~/.copilot/durable-ledger.json` for an explicit user-level configuration override
- `~/.copilot/state/durable-ledger/v1/namespaces/` for namespace directories and JSONL ledger files

Evidence that a workspace already has ledger history usually means one or more namespace directories already exist under:

```text
~/.copilot/state/durable-ledger/v1/namespaces/
```

During an active session, the active namespace also contains:

```text
.runtime-state.json
```

## Verify

1. Confirm installation:

```text
copilot plugin list
```

If you changed `hooks.json` or the scripts, reinstall the plugin before testing again:

```text
copilot plugin install /Users/chad/Repos/beu/durable-ledger/references/copilot-cli-plugin
```

2. Start a fresh Copilot CLI session.

3. Confirm the ledger root now contains:

```text
~/.copilot/state/durable-ledger/v1/namespaces/<namespace>/
```

with files such as:
- `workspaces.jsonl`
- `agents.jsonl`
- `threads.jsonl`
- `turns.jsonl`
- `events.jsonl`
- `distill_state.jsonl`
- `ledger_entries.jsonl`
- `ledger_entry_chunks.jsonl`
- `.runtime-state.json`