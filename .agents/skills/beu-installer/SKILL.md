---
name: durable-ledger-installer
description: Install or refresh the Codex durable-ledger hook bridge by writing a real hooks.json into ~/.codex/hooks.json or another Codex config layer. Use when the durable-ledger plugin is installed but not recording events, when hooks need to be activated or repaired, or when the hook command path needs to be refreshed after reinstalling the plugin.
---

# Durable Ledger Installer

Install the durable-ledger hook bridge when Codex can see the plugin but is not firing its events.

## Use the installer script

Run `python3 scripts/install_hooks.py` from this skill bundle.

Default behavior:
- write a Codex-compatible `hooks.json` to `~/.codex/hooks.json`
- preserve existing hook entries when possible
- point every hook command at the installed durable-ledger script in this plugin bundle

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
- activate the durable-ledger loop after installing or reinstalling the plugin
- repair a broken hook path after the plugin cache moved
- install the durable-ledger hooks into a different Codex config layer with `--target`

## Workflow

1. Run the installer script.
2. Confirm `codex_hooks = true` is present in `~/.codex/config.toml`.
3. If you want a repo-local hook layer, pass `--target <repo>/.codex/hooks.json`.
4. Reboot Codex if needed so it reloads the hooks config.
5. Verify that hook events now appear in the durable ledger state.

## Notes

- The script is idempotent.
- It merges with an existing hooks file instead of replacing unrelated hooks.
- The bundle still includes the hook implementation script; this skill only makes Codex discover it.
- Without the hooks feature flag, Codex may accept the plugin install but never execute the hook bridge.
