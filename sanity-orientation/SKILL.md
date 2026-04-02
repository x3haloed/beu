---
name: sanity-orientation
description: Use when the active agent must identify its live harness or determine whether a durable continuity ledger already exists before changing agent-facing state, memory, or bootstrap files.
---

# Sanity Orientation

## Overview

Before creating or editing agent state, resolve two things from live evidence:

1. What harness is shaping this session?
2. Is there already a durable ledger you can compress from?

**Core principle:** prefer observable runtime evidence over assumptions, leftovers, or repo folklore.

Use this skill for runtime identity and continuity substrate checks. Do not use it for domain behavior or ordinary repo conventions.

## When to Use

Use this skill when:
- you need to know which bootstrap surface or instruction file actually applies
- you need to decide where skills, memory, notes, or continuity artifacts belong
- you are about to modify wake-up, memory, or self-orientation behavior
- the machine or repo may support multiple agent harnesses
- you need to know whether a durable, replayable ledger already exists before compression

Do not use this skill when:
- the harness is already explicit and the task does not depend on it
- the question is about product behavior rather than agent/runtime identity

## Decision Order

Always resolve identity in this order:

1. Explicit self-identification in current instructions or session metadata
2. Live tool surface unique to the runtime or editor integration
3. Repo bootstrap files that match the live session
4. Environment variables and process context
5. Home-directory or installation traces

Always resolve durable ledger status in this order:

1. Repo-local append-only ledgers or chain systems
2. Harness-native replayable transcripts or memory with stable chronology
3. Derived summaries that point back to a real source ledger
4. Generic persistent notes or mutable memory

Stop when you have enough evidence. If stronger and weaker signals disagree, the stronger one wins. If similar-strength signals conflict, return `ambiguous` instead of guessing.

## Harness Identity

### What matters

- `harness_id` is not the same as `host_editor`.
- Provider or model metadata is not harness identity.
- `TERM_PROGRAM=vscode` identifies the editor family, not Copilot vs Cursor vs another harness.
- Repo bootstrap files are supporting evidence, not proof by themselves.
- Home-directory traces are weak because several harnesses can coexist on one machine.
- In multi-agent setups, each agent resolves its own identity from its own live session.

### Confidence rules

| Class | Meaning | Examples |
|------|---------|----------|
| High | Explicit or near-authoritative | instructions name the harness; live tool inventory is uniquely host-shaped |
| Medium | Strong but non-exclusive | repo bootstrap file matches convention; editor host matches known family |
| Low | Suggestive only | install traces, generic environment variables |

Decision rules:
- one high signal is enough if nothing equally strong contradicts it
- two medium signals that agree are enough when no high signal exists
- low signals can support but never decide
- if the only strong signal is editor family, set `host_editor` and leave `harness_id` unresolved

### Detection checklist

1. Check active instructions or session metadata for direct naming such as `Codex`, `Claude Code`, `GitHub Copilot`, `Cursor`, or `OpenClaw`.
2. Inspect the live tool surface. Unique runtime tools beat file presence.
3. Probe repo bootstrap surfaces without treating them as decisive by themselves:
   - OpenClaw: session text or tool surface; OpenClaw workspace conventions
   - GitHub Copilot: `.github/copilot-instructions.md`
   - Claude Code: `CLAUDE.md`
   - Cursor: `.cursorrules`
   - Codex or generic fallback: `AGENTS.md`
   - Custom: live contracts or repo-specific bootstrap that does not map cleanly to a known harness
4. Check environment context carefully, for example:

```bash
env | sort | grep -E '^(VSCODE|GITHUB|COPILOT|CLAUDE|CURSOR|OPENAI|CODEX|TERM_PROGRAM|TERM|SHELL)='
```

5. Treat `~/.openclaw`, `~/.copilot`, `~/.claude`, `~/.cursor`, or `~/.agents` as weak clues only.

### Harness output contract

Return:

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
notes: <caveat or next probe>
```

Rules:
- include every field every time
- keep evidence concrete and short
- prefer the narrowest truthful label
- if the bootstrap surface is not known, say `unknown`

### Quick reference

| Signal | Weight | Meaning |
|-------|--------|---------|
| Instructions explicitly name harness | High | Usually decisive |
| Live tool inventory matches a runtime family | High | Strong runtime evidence |
| Repo bootstrap file matches harness convention | Medium | Good support, not proof |
| `TERM_PROGRAM=vscode` | Medium | Host editor only |
| Harness-specific env contract | Medium | Useful support when documented |
| `~/.openclaw`, `~/.copilot`, `~/.claude`, `~/.cursor`, `~/.agents` | Low | Never decisive |

See [references/harness-signals.md](references/harness-signals.md) for the signal matrix and worked examples.

## Durable Ledger

### What counts

A durable ledger must:
- survive resets
- be readable by a future agent instance
- preserve chronology through append order, timestamps, or stable event sequence
- make corrections additive or auditable rather than silent overwrites
- preserve provenance through ids, citations, or evidence pointers

If one of those is missing, do not overclaim.

### What does not count by itself

- `AGENTS.md`, `SKILL.md`, `IDENTITY.md`, `TOOLS.md`
- `STATE.md`, `WAKE.md`, `CIL.md`, or any summary-only artifact
- vector indexes or embeddings without source history
- ephemeral session memory
- generic mutable notes
- git history alone

### Detection checklist

1. Check repo-local ledger structures first:
   - `.isnad/ledger.jsonl`
   - `.isnad/control.jsonl`
   - `CIL.md` plus source-chain pointers
   - `isnads/`, `chains/`, or another append-only chain directory
   - custom append-only logs with stable ids and evidence fields
2. Check harness-native replayable history:
   - can a future session read it again?
   - is it chronological?
   - does it have stable ids, timestamps, or citations?
   - are corrections traceable?
3. Separate memory from ledger:
   - memory answers "what should I remember?"
   - ledger answers "what happened, in what order, and why do I believe it?"
4. Determine compression readiness:
   - `yes`: durable, chronological, readable now
   - `partial`: substrate exists but needs one repair step
   - `no`: nothing reliable to compress from

### Ledger output contract

Return:

```text
ledger_status: present | repairable | absent | ambiguous
ledger_kind: isnad-chains | work-board-jsonl | harness-transcript | harness-memory | custom-append-only | none | ambiguous
durability: high | medium | low
compression_ready: yes | partial | no
paths_or_surface:
- <path or surface>
evidence:
- <short fact>
gaps:
- <missing property or "none">
notes: <caveat or next probe>
```

Rules:
- `present` means a usable chronological substrate exists now
- `repairable` means the substrate exists but one missing piece blocks safe compression
- `absent` means no durable chronological substrate was found
- `ambiguous` means persistence or chronology could not be verified strongly enough

### Quick reference

| Signal | Weight | Meaning |
|-------|--------|---------|
| `.isnad/ledger.jsonl` plus append-only contract | High | Durable ledger present |
| append-only isnad or chain history | High | Durable ledger present |
| `CIL.md` with valid source chains | Medium | Strong evidence of an underlying ledger |
| replayable harness transcript with stable ids | Medium | May qualify if chronology and reread access are real |
| mutable harness memory notes | Low | Useful support, not sufficient ledger |
| summary file with no source history | Low | Derived state only |

See [references/durable-ledger-signals.md](references/durable-ledger-signals.md) for the signal matrix and verified examples.

## Pressure Tests

| Scenario | Expected result |
|---------|-----------------|
| Instructions say GitHub Copilot and repo also has `AGENTS.md` | `harness_id: github-copilot`; `AGENTS.md` stays supporting evidence |
| Only `TERM_PROGRAM=vscode` is known | `host_editor: vscode`; `harness_id: unknown` |
| Repo has `STATE.md` and `WAKE.md` only | `ledger_status: absent` |
| Repo has `CIL.md` plus source chains or append-only ids | `ledger_status: present` or `repairable`, depending on provenance completeness |
| Live runtime conflicts with install traces | prefer live runtime and record the conflict |

## Common Mistakes

| Mistake | Better move |
|--------|-------------|
| Treating install traces as proof of the active harness | Use instructions and live tool surface first |
| Treating `TERM_PROGRAM=vscode` as proof of Copilot | Resolve editor host separately from harness |
| Guessing when signals conflict | Return `ambiguous` and name the conflict |
| Letting repo files override live runtime evidence | Treat repo files as support only |
| Returning a label without evidence | Emit the evidence list every time |
| Treating mutable memory or summary docs as a ledger | Require chronology, append order, and provenance |
| Letting another agent's notes define current identity | Resolve from the current session only |

## Worked Result Patterns

Harness example:

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
notes: install traces are non-authoritative because multiple harnesses can coexist
```

Ledger example:

```text
ledger_status: absent
ledger_kind: none
durability: low
compression_ready: no
paths_or_surface:
- harness memory scopes only
evidence:
- no `.isnad/` ledger or control files were found
- no `CIL.md` or chain directory was found
- persistent memory notes are mutable rather than append-only
gaps:
- no chronological append-only evidence plane
- no repo-local source history for future compression
notes: memory is available as a support surface, but a durable ledger still needs to be created
```
