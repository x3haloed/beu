---
name: durable-ledger
description: Use when an agent needs to configure a durable ledger in the current harness, choose a matching ledger plugin reference, or decide where durable ledger files should live.
---

# Durable Ledger

## Overview

Configure the ledger only after you know two things:

1. What harness is actually running this session.
2. Whether a durable ledger already exists.

**Core principle:** choose the plugin and storage location from live runtime facts, not from repo habit or whichever reference looks closest.

This skill is for configuring a durable ledger, not for compression or retrieval.

## When to Use

Use this skill when:
- you need to set up a durable ledger for a new harness
- the current harness does not yet have ledger storage configured
- you need to choose one of the reference plugins in this directory
- you need to decide where the ledger should live on disk

Do not use this skill when:
- you have not yet resolved the active harness
- a durable ledger is already present and only needs ordinary use
- the task is about searching or compressing a ledger rather than configuring one

## First Step

Always run [../sanity-orientation/SKILL.md](../sanity-orientation/SKILL.md) first.

You need both outputs:
- harness identity
- durable ledger status

If harness detection is `ambiguous` or `unknown`, stop and resolve that before choosing a plugin.

If ledger status is `present`, repair or extend the existing ledger instead of installing a second one.

## Plugin Selection

Pick the plugin reference from the detected harness:

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
| Copilot CLI | Do **not** assume the current working directory is the durable home. Ask the user to choose one stable home directory first |

### Copilot CLI rule

Copilot CLI does not give the agent a durable home base by default.

When configuring [references/copilot-cli-plugin](references/copilot-cli-plugin), ask the user explicitly:

```text
What directory should be my durable home base for the ledger?
Open Copilot on this home directory every time so I can always see the ledger without asking for file permissions.
```

Then place the ledger under that home directory, not under an arbitrary transient project cwd.

Good examples:
- a dedicated agent home directory chosen by the user
- a long-lived workspace root the user always opens first

Bad examples:
- `/tmp/...`
- a throwaway checkout
- whichever repo happened to be open during first install

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
| Harness is Copilot CLI | Start from [references/copilot-cli-plugin](references/copilot-cli-plugin) and ask for a durable home directory |
| Ledger already exists | Repair or extend it instead of creating a parallel ledger |

## Common Mistakes

| Mistake | Better move |
|--------|-------------|
| Picking a plugin before resolving the harness | Use [../sanity-orientation/SKILL.md](../sanity-orientation/SKILL.md) first |
| Treating GitHub Copilot in VS Code as automatically equivalent to Copilot CLI | Distinguish editor-hosted Copilot from Copilot CLI |
| Using the current cwd as the ledger root for Copilot CLI without checking | Ask the user for a stable home directory |
| Creating a second ledger beside an existing one | Repair or adopt the existing ledger |
| Choosing a storage path the agent cannot reliably reopen later | Prefer harness-owned state or a user-designated durable home |

## Worked Prompt

When Copilot CLI needs a ledger root, ask plainly:

```text
I need one stable home directory for the durable ledger.
What directory should I use as my home base?
Open Copilot on this home directory every time so I can always see the ledger without asking for file permissions.
```