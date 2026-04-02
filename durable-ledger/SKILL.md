---
name: durable-ledger
description: Use when an agent needs to configure a durable ledger in a verified harness, choose a matching ledger plugin reference, or decide where durable ledger files should live.
---

# Durable Ledger

## Overview

Configure the ledger only after you know two things:

1. What harness is actually running this session.
2. Whether a durable ledger already exists.

If the harness is not verified, stop. Do not guess a plugin, do not scan a harness-specific install directory, and do not treat one harness as the default fallback for another.

**Core principle:** choose the plugin and storage location from live runtime facts, not from repo habit or whichever reference looks closest.

This skill is for configuring a durable ledger, not for compression or retrieval.

## When to Use

Use this skill when:
- you need to set up a durable ledger for a verified harness
- the current harness does not yet have ledger storage configured
- you need to choose the reference plugin for the harness that is actually running
- you need to decide where the ledger should live on disk

Do not use this skill when:
- you have not yet resolved the active harness
- a durable ledger is already present and only needs ordinary use
- the task is about searching or compressing a ledger rather than configuring one

## First Step

Always run [../sanity-orientation/SKILL.md](../sanity-orientation/SKILL.md) first if it is available in the current checkout.
If that path is missing, resolve harness identity and ledger status from live evidence before choosing a plugin.

You need both outputs:
- harness identity
- durable ledger status

If harness detection is `ambiguous` or `unknown`, stop. Do not choose or install any harness plugin until the harness is verified.

If ledger status is `present`, repair or extend the existing ledger instead of installing a second one.

## Plugin Selection

Pick the plugin reference only from the detected harness:

| Detected harness | Reference plugin | Notes |
|------------------|------------------|-------|
| `hermes` or Hermes-compatible hook surface | [references/hermes-plugin](references/hermes-plugin) | Use when the harness exposes `pre_llm_call`, `post_llm_call`, `post_tool_call`, `on_session_start`, `on_session_end` |
| `openclaw` | [references/openclaw-plugin](references/openclaw-plugin) | Use when the harness exposes `llm_input`, `llm_output`, `after_tool_call` via the OpenClaw memory plugin contract |
| GitHub Copilot CLI | [references/copilot-cli-plugin](references/copilot-cli-plugin) | Use when the harness is Copilot CLI with `plugin.json` and `hooks.json` support |

Do not force a plugin choice from a weak signal.

If the harness is GitHub Copilot in VS Code editor mode rather than Copilot CLI, this reference set does not automatically imply a CLI plugin install. Distinguish editor-hosted Copilot from Copilot CLI before choosing [references/copilot-cli-plugin](references/copilot-cli-plugin).

## Storage Location

Choose the ledger root by stability first, convenience second.

The ledger root should be:
- readable on every future session start
- stable across resets and restarts
- inside a directory the agent can access without repeated permission friction
- specific enough to avoid cross-project collisions

### Preferred defaults

| Harness | Default storage rule |
|---------|----------------------|
| Hermes | Prefer the harness-owned state location, typically `${HERMES_HOME}/state/durable-ledger`, unless the user already has a repo or workspace home for the agent |
| OpenClaw | Prefer the configured plugin `storageRoot` or the harness-owned state directory |
| GitHub Copilot CLI | Use the fixed per-user root `~/.copilot/state/durable-ledger` unless an explicit Copilot durable-ledger override is already present |

### Hermes rule

Only when the verified harness is Hermes or Hermes-compatible, install the reference plugin into the user plugin root and verify it by exercising a real turn path:

1. Install the plugin from this directory into `${HERMES_HOME:-~/.hermes}/plugins/durable-ledger`.
2. Start a fresh Hermes session so discovery rescans the user plugin root.
3. Confirm `discover_plugins()` or `get_plugin_manager().list_plugins()` shows `durable-ledger` as enabled.
4. Invoke `pre_llm_call` / `post_llm_call` with a representative `user_message` and `assistant_response`.
5. Confirm JSONL files appear under `${HERMES_HOME:-~/.hermes}/state/durable-ledger/v1/namespaces/<namespace>/`.

If the host CLI is unavailable or awkward to reach, use the direct-hook fallback in the durable-ledger-verification skill.

### GitHub Copilot CLI rule

Only when the verified harness is GitHub Copilot CLI, use a stable plugin install path and the fixed Copilot-owned ledger root:

1. Install the plugin from this directory only after harness verification, for example:

   ```text
   copilot plugin install /Users/chad/Repos/beu/durable-ledger/references/copilot-cli-plugin
   ```

   Important:
   - Use `copilot plugin install`, not `copilot install`.
   - The installed CLI help on this machine does not advertise local-path installs, but the command does work with an absolute local path.
   - If the agent is unsure, prefer an absolute path over a relative path.

2. The plugin writes by default under:

   ```text
   ~/.copilot/state/durable-ledger/v1/namespaces/<workspace-namespace>/
   ```

   The namespace is derived from a stable workspace root resolved from the current `cwd` by walking upward until a common project marker such as `.git`, `pyproject.toml`, `package.json`, `Cargo.toml`, or `go.mod` is found.

3. If you need to override that without changing how Copilot is launched, create:

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

4. Start a fresh Copilot CLI session. The hooks derive the namespace from the session `cwd` and common project markers, while storage stays under the fixed Copilot-owned root unless overridden.

5. When checking for evidence of an existing GitHub Copilot CLI ledger install, look in this order:

   ```text
   copilot plugin list
   ~/.copilot/installed-plugins/
   ~/.copilot/durable-ledger.json
   ~/.copilot/state/durable-ledger/v1/namespaces/
   ```

The first `session-start` hook creates:

```text
workspaces.jsonl
agents.jsonl
threads.jsonl
turns.jsonl
events.jsonl
distill_state.jsonl
ledger_entries.jsonl
ledger_entry_chunks.jsonl
.runtime-state.json
```

For a verified GitHub Copilot CLI harness, confirm that `copilot plugin list` shows `durable-ledger`, then trigger a new session and check that the namespace directory exists and the files above are created.

Good examples:
- the fixed Copilot-owned state directory under `~/.copilot/state/durable-ledger` when the verified harness is GitHub Copilot CLI
- a user-level override in `~/.copilot/durable-ledger.json` when the verified harness is GitHub Copilot CLI and the default root or namespace needs adjustment

Bad examples:
- `/tmp/...`
- a throwaway checkout as the storage root
- asking the user to choose a home directory for ordinary Copilot CLI use

## Configuration Pattern

1. Resolve the harness with [../sanity-orientation/SKILL.md](../sanity-orientation/SKILL.md).
2. Check whether a durable ledger already exists.
3. If absent, choose the matching reference plugin.
4. Pick the most stable ledger root for that harness.
5. Configure the plugin to write there.
6. Verify that the hook surface can append JSONL files in that location.

Do not configure multiple ledger roots for the same live harness unless the user explicitly wants namespace separation.

## Quick Reference

| Situation | Correct move |
|-----------|--------------|
| Harness is unresolved | Run [../sanity-orientation/SKILL.md](../sanity-orientation/SKILL.md) first |
| Harness is Hermes | Start from [references/hermes-plugin](references/hermes-plugin) |
| Harness is OpenClaw | Start from [references/openclaw-plugin](references/openclaw-plugin) |
| Harness is GitHub Copilot CLI | Start from [references/copilot-cli-plugin](references/copilot-cli-plugin) and check `~/.copilot` for an existing plugin install, config override, or ledger root |
| Ledger already exists | Repair or extend it instead of creating a parallel ledger |

## Common Mistakes

| Mistake | Better move |
|--------|-------------|
| Picking a plugin before resolving the harness | Use [../sanity-orientation/SKILL.md](../sanity-orientation/SKILL.md) first |
| Treating GitHub Copilot in VS Code as automatically equivalent to Copilot CLI | Distinguish editor-hosted Copilot from Copilot CLI |
| Assuming install alone proves the Hermes ledger is working | Verify a real user turn and confirm the JSONL files were written |
| Using the current cwd itself as the ledger root for GitHub Copilot CLI | Use the fixed root under `~/.copilot/state/durable-ledger` |
| Choosing a storage path the agent cannot reliably reopen later | Prefer harness-owned state or a user-level Copilot override |
