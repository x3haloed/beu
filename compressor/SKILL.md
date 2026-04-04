---
name: compressor
description: Use when a compressor needs to be installed, reinstalled, or verified for either Copilot or Codex scheduling, including the isolated Codex home setup that refreshes wake packs without reusing the regular Codex runtime home.
---

# Compressor

## Overview

This skill covers the scheduled compressor path for both backends.

The compressor runs on a schedule, uses the installed compressor prompt, and overwrites one of these backend-specific publication surfaces:

- Copilot: `<stable-home>/.github/copilot-instructions.md`
- Codex: `<ledger-namespace>/wake-pack.md`

For the Codex backend, the scheduled run uses an isolated `CODEX_HOME` by default and writes the published wake pack to:

```text
<ledger-namespace>/wake-pack.md
```

The stable home directory is the root the published output lives under. It is not the same thing as the isolated Codex execution home.

**Core principle:** treat installation state as an evidence question first. Do not reinstall blindly if the compressor is already present and correctly wired.

## When to Use

Use this skill when:
- you need to determine whether the compressor is already installed
- you need to install or reinstall the compressor for a stable home directory
- you need to inspect the scheduled job, runner config, or copied prompt files
- you need to verify that the compressor updates the expected publication surface

Do not use this skill when:
- the task is to design the wake-pack schema itself
- the task is to configure durable-ledger capture rather than compression
- the task is unrelated to the scheduled compressor workflow

## First Step

Always resolve the harness first.

If [../sanity-orientation/SKILL.md](../sanity-orientation/SKILL.md) is available, use it before touching compressor state.

Proceed only when the harness and backend are verified.

If the harness is unresolved or the backend choice is ambiguous, stop and resolve that first.

## Supported Start States

This skill assumes one of these initial states:

1. `unsure-if-installed`
2. `sure-not-installed`

Handle them differently.

## State: `unsure-if-installed`

When installation state is uncertain, inspect live evidence in this order:

1. Check that the stable home directory is known.
2. Check for copied compressor files under:

   ```text
   <stable-home>/.beu/compressor/
   ```

   Expected files:

   ```text
   compressor-prompt.txt
   <backend>_compressor_runner.py
   <backend>-compressor.json
   ```

3. Read:

   ```text
   <stable-home>/.beu/compressor/<backend>-compressor.json
   ```

   Verify that:
   - `homeDir` matches the intended stable home
   - `outputPath` points to the expected publication surface for the backend
   - `promptPath` and `logPath` point into `<stable-home>/.beu/compressor/`
   - if the backend is Codex, `codexHomeDir` resolves to the isolated execution home, not the stable home

4. Check whether a scheduler entry exists for that home:

   - macOS `launchd`:

     ```text
     ~/Library/LaunchAgents/com.beu.<backend>-compressor.<slug>.plist
     ```

   - Linux `cron`:

     search `crontab -l` for:

     ```text
     # BEGIN com.beu.<backend>-compressor.<slug>
     ```

   - Windows Task Scheduler:

     task name:

     ```text
     com.beu.<backend>-compressor.<slug>
     ```

5. Check whether the output surface exists:

   - Copilot: `<stable-home>/.github/copilot-instructions.md`
   - Codex: `<ledger-namespace>/wake-pack.md`

6. If present, check the log file for recent runs:

   ```text
   <stable-home>/.beu/compressor/<backend>-compressor.log
   ```

### Decision rule for `unsure-if-installed`

Treat the compressor as `installed` only when both are true:
- the copied runner/config files exist and match the intended stable home
- the scheduler entry exists for that same home

Treat it as `stale-or-partial` when some evidence exists but does not line up cleanly.

Treat it as `not-installed` when neither the copied files nor scheduler evidence exists.

If the state is `stale-or-partial`, reinstall cleanly rather than trying to patch the old install in place.

## State: `sure-not-installed`

When the compressor is known to be absent, install it directly.

You do not need to scan every scheduler surface first.

You do need to confirm the stable home directory because the compressor overwrites:

```text
<stable-home>/.github/copilot-instructions.md
```

## Install Procedure

Use the installer in:

```text
references/install_scheduled_compressor.py
```

Run it with the stable home directory:

```text
python3 /Users/chad/Repos/beu/compressor/references/install_scheduled_compressor.py --home-dir <stable-home> --backend <codex|copilot>
```

Notes:
- On macOS, the default scheduler is `launchd`.
- On Linux, the default scheduler is `cron`.
- On Windows, the default scheduler is Task Scheduler via `schtasks`.
- For the Codex backend, the installer also creates a separate isolated `CODEX_HOME` and symlinks in the existing Codex auth file before invoking `codex exec`.
- If an older install already exists for the same home, the installer removes the old scheduled job first and installs the new one in its place.

## Reinstall Rule

If the compressor is present but stale, inconsistent, or pointed at the wrong home directory, reinstall it instead of editing files by hand.

The installer is designed to replace the prior scheduler registration for the same home.

## Verification

After install or reinstall, verify all of the following:

1. The copied files exist under:

   ```text
   <stable-home>/.beu/compressor/
   ```

2. The config file points at the correct output target:

   - Copilot: `<stable-home>/.github/copilot-instructions.md`
   - Codex: `<ledger-namespace>/wake-pack.md`

3. The scheduler entry exists for the stable home.

4. The runner log file exists or is writable:

   ```text
   <stable-home>/.beu/compressor/<backend>-compressor.log
   ```

5. A test run can refresh `.github/copilot-instructions.md`.

## Quick Reference

| Situation | Correct move |
|-----------|--------------|
| Harness or backend is not verified | Stop and resolve identity first |
| Unsure whether compressor is installed | Check copied files, config, scheduler entry, and output surface |
| Sure the compressor is not installed | Run the installer directly |
| Compressor evidence exists but is inconsistent | Reinstall cleanly |
| Stable home directory is unknown | Stop and resolve the home directory before installing |

## Common Mistakes

| Mistake | Better move |
|--------|-------------|
| Installing before verifying the harness/backend | Confirm the target backend first |
| Treating a scheduler entry alone as proof of a healthy install | Check copied files and config too |
| Editing scheduler files manually when the install is stale | Reinstall with the installer |
| Pointing the compressor at a transient cwd | Use the stable home directory the published output should live under |
| Forgetting that the compressor overwrites the backend publication surface | Treat the stable home and output file as the primary published surface |

## Output Contract

When using this skill, report compressor state in this form:

```text
compressor_state: installed | stale-or-partial | not-installed | ambiguous
stable_home: <path or unknown>
runner_files:
- <path>
scheduler_surface: <launchd plist | cron marker | schtasks name | none>
output_surface: <path>
recommended_action: verify | install | reinstall | stop
notes: <short caveat>
```
