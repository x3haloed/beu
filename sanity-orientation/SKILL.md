---
name: sanity-orientation
description: Use when an agent must establish what harness it is running inside before choosing bootstrap files, memory surfaces, or self-modification paths.
---

# Sanity Orientation

## Overview

Before building state for yourself, identify the container you are inside.

**Core principle:** Resolve the harness from observable evidence, not from assumptions or a single convenient clue.

This first primitive answers only one question:

**What agent harness is this?**

## When to Use

Use this skill when:
- You need to know which bootstrap file the harness auto-injects
- You need to decide where skills, memory, or generated state should live
- You are about to modify agent-facing instructions for continuity or wake-up behavior
- The repo may be opened by multiple harnesses and the right path depends on the active one

Do not use this skill when:
- The harness is already explicitly known and the task does not depend on it
- You are deciding domain behavior rather than environment identity

## Detection Order

Always resolve in this order:

1. Direct self-identification from the current instructions or session metadata
2. Tooling surface unique to the host or editor integration
3. Repo bootstrap files and harness-specific instruction surfaces
4. Environment variables and process context
5. User-home directories or local installation traces

Start at the top and stop as soon as you have a high-confidence answer.

## Confidence Rules

Use these evidence classes:

| Class | Meaning | Examples |
|------|---------|----------|
| High | Explicit or near-authoritative signal | System or developer instructions name the harness; tool inventory is uniquely host-shaped |
| Medium | Strong but non-exclusive signal | Bootstrap file matches known harness convention; editor context matches host family |
| Low | Suggestive only | Home directories, config remnants, generic environment variables |

Decision rules:
- One high-confidence signal is enough if nothing contradicts it.
- Two medium signals that agree are enough when no high signal exists.
- Low signals never decide the harness on their own.
- If signals conflict, report `ambiguous` and list the conflict instead of guessing.

## Output Contract

Return the result in a compact structure the agent can reuse:

```text
harness_id: github-copilot | claude-code | cursor | codex | unknown | ambiguous
host_editor: vscode | terminal | unknown
confidence: high | medium | low
evidence:
- <short fact>
- <short fact>
bootstrap_surface: <path or convention>
notes: <ambiguity, caveat, or next probe>
```

## Procedure

### 1. Check for explicit self-identification

Look for statements in the active instructions or session metadata that directly name the harness.

Examples:
- "Your name is GitHub Copilot"
- "Use Skills in Claude Code"
- "Codex"

If present, treat that as the primary signal.

### 2. Inspect the tool surface

Look at the tools the harness exposes.

Examples:
- VS Code-specific tools such as `run_vscode_command`, `get_vscode_api`, `vscode_askQuestions`, notebook editing, or editor-bound browser controls imply a VS Code host family.
- A Codex-specific environment variable or CLI contract can point toward Codex when explicit naming is absent.

Tool surface is stronger than file presence because it reflects the live runtime, not leftover config.

### 3. Check the bootstrap surface the repo expects

Known defaults in this repo:
- GitHub Copilot: `.github/copilot-instructions.md`
- Claude Code: `CLAUDE.md`
- Cursor: `.cursorrules`
- Generic or Codex-style fallback: `AGENTS.md`

This is useful when the repo is prepared for one harness, but it is still not fully authoritative by itself.

### 4. Probe environment context

Use broad shell primitives, not harness-specific assumptions.

Examples:

```bash
env | sort | grep -E '^(VSCODE|GITHUB|COPILOT|CLAUDE|CURSOR|OPENAI|CODEX|TERM_PROGRAM|TERM|SHELL)='
```

Interpret carefully:
- `TERM_PROGRAM=vscode` tells you the editor host is VS Code, not whether it is Copilot or Cursor.
- Missing variables do not disprove a harness.

### 5. Treat installation traces as weak evidence only

User-home directories such as `~/.copilot`, `~/.claude`, `~/.cursor`, or `~/.agents` are weak clues.

They often coexist. Their presence means "installed sometime" not "currently running here."

## Quick Reference

| Signal | Weight | Meaning |
|-------|--------|---------|
| Instructions explicitly name harness | High | Usually decisive |
| Live tool inventory matches a host family | High | Strong runtime evidence |
| Repo bootstrap file matches harness convention | Medium | Good supporting evidence |
| `TERM_PROGRAM=vscode` | Medium | VS Code host only |
| `CODEX_CI=1` or similar harness env | Medium | Useful when explicit |
| `~/.copilot`, `~/.claude`, `~/.cursor` | Low | Never decisive |

## Known Bootstrap Targets

See [references/harness-signals.md](references/harness-signals.md) for the current signal matrix and worked example.

## Common Mistakes

| Mistake | Better move |
|--------|-------------|
| Treating a home directory as proof of the active harness | Use live instructions and tool surface first |
| Treating `TERM_PROGRAM=vscode` as proof of Copilot | Resolve editor host separately from harness |
| Guessing when signals conflict | Return `ambiguous` and say what disagrees |
| Looking only at repo files | Check the live runtime before assuming the repo setup matches it |
| Returning a label without evidence | Emit the evidence list every time |

## Worked Result Pattern

When you finish, say the answer plainly:

```text
harness_id: github-copilot
host_editor: vscode
confidence: high
evidence:
- active instructions identify the agent as GitHub Copilot
- live tool surface includes VS Code editor integration tools
- TERM_PROGRAM=vscode confirms the host editor family
bootstrap_surface: .github/copilot-instructions.md
notes: home-directory checks are non-authoritative because multiple harness traces can coexist
```