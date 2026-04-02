---
name: compressor
description: Use when a GitHub Copilot CLI session needs to determine whether the compressor is already installed for a stable home directory, install or reinstall it, or verify the scheduled compressor path that refreshes .github/copilot-instructions.md.
---

# Compressor

## Overview

This skill is for the Copilot-first compressor path.

The compressor runs on a schedule, invokes `copilot -p` with the installed compressor prompt, and overwrites:

```text
<stable-home>/.github/copilot-instructions.md
```

The stable home directory is the root the user must keep launching Copilot from.

**Core principle:** treat installation state as an evidence question first. Do not reinstall blindly if the compressor is already present and correctly wired.

## When to Use

Use this skill when:
- you need to determine whether the Copilot compressor is already installed
- you need to install or reinstall the Copilot compressor for a stable home directory
- you need to inspect the scheduled job, runner config, or copied prompt files
- you need to verify that the compressor updates `.github/copilot-instructions.md`

Do not use this skill when:
- the task is to design the wake-pack schema itself
- the task is to configure durable-ledger capture rather than compression
- the harness is not GitHub Copilot CLI

## First Step

Always resolve the harness first.

If [../sanity-orientation/SKILL.md](../sanity-orientation/SKILL.md) is available, use it before touching compressor state.

Proceed only when the harness is verified as GitHub Copilot CLI.

If the harness is unresolved, ambiguous, or editor-hosted Copilot rather than Copilot CLI, stop and resolve that first.

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
   copilot_compressor_runner.py
   copilot-compressor.json
   ```

3. Read:

   ```text
   <stable-home>/.beu/compressor/copilot-compressor.json
   ```

   Verify that:
   - `homeDir` matches the intended stable home
   - `outputPath` points to `<stable-home>/.github/copilot-instructions.md`
   - `promptPath` and `logPath` point into `<stable-home>/.beu/compressor/`

4. Check whether a scheduler entry exists for that home:

   - macOS `launchd`:

     ```text
     ~/Library/LaunchAgents/com.beu.copilot-compressor.<slug>.plist
     ```

   - Linux `cron`:

     search `crontab -l` for:

     ```text
     # BEGIN com.beu.copilot-compressor.<slug>
     ```

   - Windows Task Scheduler:

     task name:

     ```text
     com.beu.copilot-compressor.<slug>
     ```

5. Check whether the output surface exists:

   ```text
   <stable-home>/.github/copilot-instructions.md
   ```

6. If present, check the log file for recent runs:

   ```text
   <stable-home>/.beu/compressor/copilot-compressor.log
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
references/install_copilot_compressor.py
```

Run it with the stable home directory:

```text
python3 /Users/chad/Repos/beu/compressor/references/install_copilot_compressor.py --home-dir <stable-home>
```

Notes:
- On macOS, the default scheduler is `launchd`.
- On Linux, the default scheduler is `cron`.
- On Windows, the default scheduler is Task Scheduler via `schtasks`.
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

   ```text
   <stable-home>/.github/copilot-instructions.md
   ```

3. The scheduler entry exists for the stable home.

4. The runner log file exists or is writable:

   ```text
   <stable-home>/.beu/compressor/copilot-compressor.log
   ```

5. A test run can refresh `.github/copilot-instructions.md`.

## Quick Reference

| Situation | Correct move |
|-----------|--------------|
| Harness is not verified as GitHub Copilot CLI | Stop and resolve harness identity first |
| Unsure whether compressor is installed | Check copied files, config, scheduler entry, and output surface |
| Sure the compressor is not installed | Run the installer directly |
| Compressor evidence exists but is inconsistent | Reinstall cleanly |
| Stable home directory is unknown | Stop and resolve the home directory before installing |

## Common Mistakes

| Mistake | Better move |
|--------|-------------|
| Installing before verifying the harness | Confirm GitHub Copilot CLI first |
| Treating a scheduler entry alone as proof of a healthy install | Check copied files and config too |
| Editing scheduler files manually when the install is stale | Reinstall with the installer |
| Pointing the compressor at a transient cwd | Use the stable home directory the user will keep launching Copilot from |
| Forgetting that the compressor overwrites `.github/copilot-instructions.md` | Treat the stable home and output file as the primary published surface |

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