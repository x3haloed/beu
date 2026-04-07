---
name: durable-ledger-installer
description: Install or refresh the Codex session-start hook that injects the computed BEU agent state from ~/.beu/compute-agent-state.js into Codex context.
---

# BEU Hook Installer

Install the Codex session-start hook that loads the computed BEU agent state into context.

## Use the installer script

Run `node scripts/install_hooks.js` from this skill bundle.

Default behavior:
- write a Codex-compatible `hooks.json` to `~/.codex/hooks.json`
- preserve existing hook entries when possible
- remove this installer's previously managed Codex hook events and replace them with a `SessionStart` hook
- point the hook command at the installed `~/.beu/compute-agent-state.js`
- read the canonical delta log from `~/.beu/state/deltas.jsonl`

## Enable Codex hooks

This bridge only works if Codex hooks are enabled globally.

Make sure `~/.codex/config.toml` contains:

```toml
[features]
codex_hooks = true
```

If that flag is missing, add it before you consider the install complete. The hook file alone is not enough.

## When to use it

Use this skill when you need to:
- activate session-start state injection after installing or reinstalling the plugin
- repair a broken hook path after the installed `~/.beu` files moved or were refreshed
- install the durable-ledger hooks into a different Codex config layer with `--target`

## Workflow

1. Run the installer script.
2. Confirm `codex_hooks = true` is present in `~/.codex/config.toml`.
3. If you want a repo-local hook layer, pass `--target <repo>/.codex/hooks.json`.
4. Reboot Codex if needed so it reloads the hooks config.
5. Verify that `SessionStart` now injects the computed state into Codex context.

## Notes

- The script is idempotent.
- It merges with an existing hooks file instead of replacing unrelated hooks.
- The installed hook prints the state program's stdout as plain text developer context.
- Without the hooks feature flag, Codex may accept the plugin install but never execute the hook bridge.
