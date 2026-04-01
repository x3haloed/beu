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

This skill is about runtime identity, not repo preference. A machine can contain traces of several frameworks at once. The goal is to identify the one that is actually shaping the current session.

## Important Distinctions

- `harness_id` is not the same as `host_editor`.
- Provider/model metadata is not harness identity. A session can say `Provider: openai-codex` while the actual harness is OpenClaw, Codex, or another wrapper.
- `TERM_PROGRAM=vscode` can identify the editor family, but it does not prove Copilot vs Cursor vs another harness.
- Repo bootstrap files are supporting evidence, not proof by themselves. Their presence only matters when they match the repo's expected harness surface.
- Home-directory traces are weak because multiple harnesses can coexist on one machine.
- Coordination between multiple agents does not merge identities. Each agent must resolve its own harness from its own live session evidence.

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
3. Repo bootstrap files and harness-specific instruction surfaces (supporting evidence only)
4. Environment variables and process context
5. User-home directories or local installation traces

Start at the top and stop as soon as you have a decisive answer. If higher-priority evidence conflicts with lower-priority evidence, prefer the higher-priority evidence and record the conflict. If two signals at the same meaningful tier disagree, report `ambiguous` rather than forcing a guess. If you exhaust the sequence without enough evidence, return `unknown` with the strongest facts you found.

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

Apply the classes in this strict order:
1. Explicit self-identification
2. Live tool surface
3. Repo bootstrap files
4. Environment variables
5. Home-directory traces

Interpretation rules:
- Explicit self-identification overrides all weaker classes unless another equally explicit signal disagrees.
- One high-confidence signal is decisive.
- Two medium-confidence signals that agree are sufficient.
- Low-confidence signals can support a result but never decide one.
- Conflicts between signals of similar weight must return `ambiguous`.
- Do not average contradictory evidence into a guess.

## Output Contract

Return the result in a compact structure the agent can reuse:

```text
harness_id: openclaw | github-copilot | claude-code | cursor | codex | custom | unknown | ambiguous
host_editor: vscode | terminal | unknown
confidence: high | medium | low
evidence:
- <short fact>
- <short fact>
bootstrap_surface: <path or convention>
conflicts:
- <short conflict or "none">
notes: <ambiguity, caveat, or next probe>
```

## Procedure

### 1. Check for explicit self-identification

Look for statements in the active instructions or session metadata that directly name the harness.

Examples:
- `OpenClaw`
- "Your name is GitHub Copilot"
- "Use Skills in Claude Code"
- "Codex"

If present, treat that as the primary signal.

### 2. Inspect the tool surface

Look at the tools the harness exposes.

Examples:
- OpenClaw-specific tool names, startup contracts, or runtime surfaces point toward OpenClaw.
- VS Code-specific tools such as `run_vscode_command`, `get_vscode_api`, `vscode_askQuestions`, notebook editing, or editor-bound browser controls imply a VS Code host family.
- A Codex-specific environment variable or CLI contract can point toward Codex when explicit naming is absent.
- A tool surface that does not match any known harness should be treated as evidence for `custom`, not forced into the closest familiar bucket.

Tool surface is stronger than file presence because it reflects the live runtime, not leftover config.

### 3. Detect framework-specific bootstrap surfaces

Probe for known framework signatures without assuming that file presence alone is decisive.

OpenClaw checks:
- OpenClaw-specific instructions or bootstrap text in the current session
- OpenClaw workspace conventions such as `~/.openclaw/workspace/AGENTS.md`, `IDENTITY.md`, `TOOLS.md`, or `openclaw.json`
- OpenClaw-native tool or command naming that appears in the live runtime

GitHub Copilot checks:
- `.github/copilot-instructions.md`
- Copilot-specific self-identification in instructions
- VS Code-linked Copilot tool surfaces

Claude Code checks:
- `CLAUDE.md`
- Claude Code self-identification or skill-loading instructions
- Claude-specific tool or command surfaces

Cursor checks:
- `.cursorrules`
- Cursor self-identification
- Cursor-specific editor/runtime signals

Codex checks:
- `AGENTS.md`
- Codex self-identification in instructions
- Codex-native tool contracts or environment conventions

Custom harness checks:
- A repo-specific bootstrap file that does not map cleanly to a known harness
- A tool surface that is clearly live but not recognizable as a known framework
- Local configuration or session contracts that define capabilities without matching known defaults

### 4. Check the bootstrap surface the repo expects

Known defaults in this repo:
- OpenClaw-style sessions: OpenClaw instruction surfaces plus the live OpenClaw runtime
- GitHub Copilot: `.github/copilot-instructions.md`
- Claude Code: `CLAUDE.md`
- Cursor: `.cursorrules`
- Generic or Codex-style fallback: `AGENTS.md`

This is useful when the repo is prepared for one harness, but it is still not fully authoritative by itself.

### 5. Probe environment context

Use broad shell primitives, not harness-specific assumptions.

Examples:

```bash
env | sort | grep -E '^(VSCODE|GITHUB|COPILOT|CLAUDE|CURSOR|OPENAI|CODEX|TERM_PROGRAM|TERM|SHELL)='
```

Interpret carefully:
- `TERM_PROGRAM=vscode` tells you the editor host is VS Code, not whether it is Copilot or Cursor.
- Missing variables do not disprove a harness.
- Generic variables such as `OPENAI_*` or shell state are supporting evidence only unless the runtime documents them as harness-specific.

### 6. Treat installation traces as weak evidence only

User-home directories such as `~/.openclaw`, `~/.copilot`, `~/.claude`, `~/.cursor`, or `~/.agents` are weak clues.

They often coexist. Their presence means "installed sometime" not "currently running here."

### 7. Verify identity isolation in multi-agent scenarios

If the environment suggests several agents or orchestration layers are active:
- Resolve the current agent from the current session only.
- Do not inherit another agent's identity from shared files, logs, or coordination transcripts.
- Distinguish shared machine state from live session state.
- Treat cross-agent notes as context, not proof of the present harness.

If shared artifacts suggest one harness but the live session tools suggest another, return `ambiguous` or prefer the live session if its evidence is strictly stronger.

## Quick Reference

| Signal | Weight | Meaning |
|-------|--------|---------|
| Instructions explicitly name harness | High | Usually decisive |
| Live tool inventory matches a host family | High | Strong runtime evidence |
| OpenClaw runtime surface or OpenClaw-native bootstrap contract | High | OpenClaw harness |
| Repo bootstrap file matches harness convention | Medium | Good supporting evidence |
| `TERM_PROGRAM=vscode` | Medium | VS Code host only |
| `CODEX_CI=1` or similar harness env | Medium | Useful when explicit |
| `~/.openclaw`, `~/.copilot`, `~/.claude`, `~/.cursor`, `~/.agents` | Low | Never decisive |

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
| Letting another agent's notes define your identity | Resolve from your own live session and treat shared artifacts as secondary evidence |

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
conflicts:
- none
notes: home-directory checks are non-authoritative because multiple harness traces can coexist
```
