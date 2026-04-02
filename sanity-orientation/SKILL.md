---
name: sanity-orientation
description: Use when an agent must establish what harness it is running inside, whether a durable ledger already exists, or where continuity artifacts should live before self-modification.
---

# Sanity Orientation

## Overview

Before building state for yourself, identify the container you are inside.

**Core principle:** Resolve the harness from observable evidence, not from assumptions or a single convenient clue.

This skill currently answers two questions:

**What agent harness is this?**

**Do I already have a durable ledger?**

This skill is about runtime identity, not repo preference. A machine can contain traces of several frameworks at once. The goal is to identify the one that is actually shaping the current session.

## Important Distinctions

- `harness_id` is not the same as `host_editor`.
- Provider/model metadata is not harness identity. A session can say `Provider: openai-codex` while the actual harness is OpenClaw, Codex, or another wrapper.
- `TERM_PROGRAM=vscode` can identify the editor family, but it does not prove Copilot vs Cursor vs another harness.
- Repo bootstrap files are supporting evidence, not proof by themselves. Their presence only matters when they match the repo's expected harness surface.
- Home-directory traces are weak because multiple harnesses can coexist on one machine.
- Coordination between multiple agents does not merge identities. Each agent must resolve its own harness from its own live session evidence.
- A bootstrap file can inform the expected surface, but the live session always wins when they disagree.
- If the evidence only identifies the editor host, report the editor host and keep `harness_id` separate.
- Durable ledger is not the same as "persistent memory." A notes store that can be overwritten is useful, but it is not automatically a ledger.
- A summary file such as `STATE.md`, `WAKE.md`, or `CIL.md` is not itself the ledger unless it also preserves chronological source history.
- Compression artifacts are derived state. The ledger is the substrate they are derived from.
- Git history is useful evidence, but it is not a general agent ledger for instructions, tool outputs, and decisions unless the system explicitly treats commits as that ledger.

## When to Use

Use this skill when:
- You need to know which bootstrap file the harness auto-injects
- You need to decide where skills, memory, or generated state should live
- You are about to modify agent-facing instructions for continuity or wake-up behavior
- The repo may be opened by multiple harnesses and the right path depends on the active one

Do not use this skill when:
- The harness is already explicitly known and the task does not depend on it
- You are deciding domain behavior rather than environment identity

If you are uncertain whether the task is about identity or repo conventions, resolve identity first and defer path decisions until the harness is known.

## Detection Order

Always resolve in this order:

1. Direct self-identification from the current instructions or session metadata
2. Tooling surface unique to the host or editor integration
3. Repo bootstrap files and harness-specific instruction surfaces (supporting evidence only)
4. Environment variables and process context
5. User-home directories or local installation traces

Start at the top and stop as soon as you have a decisive answer. If higher-priority evidence conflicts with lower-priority evidence, prefer the higher-priority evidence and record the conflict. If two signals at the same meaningful tier disagree, report `ambiguous` rather than forcing a guess. If you exhaust the sequence without enough evidence, return `unknown` with the strongest facts you found.

Decision shortcut:

1. If the instructions explicitly name the harness, use that.
2. Else if the live tool surface is uniquely harness-shaped, use that.
3. Else if two medium signals agree, use that.
4. Else return `ambiguous` or `unknown` rather than filling in gaps.

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
- If the only strong signal is about the editor family, set `host_editor` and leave `harness_id` unresolved unless another signal distinguishes the harness.

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

Output rules:
- Always include every field, even when the answer is `unknown`.
- Keep evidence short and concrete.
- Prefer the narrowest truthful label over an aspirational guess.
- If `bootstrap_surface` is not known, say `unknown` rather than inventing a conventional path.

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
Do not infer a harness from generic editor affordances alone unless the tool surface is actually harness-specific.

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
If the repo contains several possible bootstrap files, prefer the one that matches the live session rather than the oldest or most familiar one.

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
| Using repo files to override live runtime evidence | Treat repo files as supporting evidence only |
| Collapsing editor host into harness identity | Report `host_editor` separately from `harness_id` |

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

## Durable Ledger

Before building continuity, determine whether there is already a persistent substrate you can compress from.

**Core principle:** A durable ledger must survive resets and preserve enough chronology and provenance to reconstruct what happened later.

A ledger is durable enough when all of these are true:
- It survives session or process resets.
- A future agent instance can read it again.
- It preserves append order, timestamps, or another trustworthy event sequence.
- Corrections are additive or auditable rather than silent overwrites.
- It can carry evidence pointers, source ids, or concrete provenance.

If one of those is missing, do not overclaim. Report the gap.

### Durable Ledger Output Contract

Return the result in this structure:

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

Output rules:
- `present` means there is already a usable chronological substrate.
- `repairable` means there is a durable substrate, but one missing piece blocks immediate compression.
- `absent` means no durable chronological substrate was found.
- `ambiguous` means you cannot verify persistence or sequence strongly enough.

### Detection Order For Durable Ledger

Resolve in this order:

1. Repo-local append-only ledgers and chain systems
2. Harness-native transcript or memory surfaces with stable replay
3. Derived state or summaries that point back to a real ledger
4. Generic persistent notes or mutable memory stores

Start with repo-local evidence because it is inspectable, portable, and under agent control.

### What Counts As A Durable Ledger

High-confidence ledger forms:
- `.isnad/ledger.jsonl` and `.isnad/control.jsonl` with append-only semantics
- isnad markdown chains that are explicitly append-only
- a repo-local custom log with stable ids and additive corrections
- a harness transcript API that exposes durable chronological history with stable ids and later re-read access

Medium-confidence forms:
- harness memory that survives resets and preserves chronology, but is mutable or only partially auditable
- a repo-local log that is persistent and chronological but lacks explicit correction protocol

Not a ledger by itself:
- `AGENTS.md`, `SKILL.md`, `IDENTITY.md`, `TOOLS.md`
- `STATE.md`, `WAKE.md`, `CIL.md`, or any other summary-only artifact
- vector indexes, embeddings, or search indexes without source history
- ephemeral session memory
- generic user memory notes that can be edited or replaced silently
- git history alone

### Procedure

#### 1. Check for repo-native ledger structures

Look for the strongest forms first:
- `.isnad/ledger.jsonl`
- `.isnad/control.jsonl`
- `CIL.md` plus a `cil_paths` header pointing to isnads or chains
- `isnads/`, `chains/`, or another append-only chain directory
- custom append-only logs with record ids and evidence fields

Interpretation rules:
- `CIL.md` without source chains is not enough. It is compiled state, not the ledger.
- `.isnad/state/*` is derived state, not the ledger.
- If the ledger exists but a derived file is missing, the ledger is still present.

#### 2. Check for harness-native replayable history

Some harnesses provide persistence, but persistence alone is not enough.

Ask:
- Can a future session read the same history again?
- Are entries chronological?
- Do entries have stable ids, timestamps, or citations?
- Can corrections be traced, or does the system silently rewrite?

If the answer is "persistent but mutable notes only," classify it as support, not a durable ledger.

#### 3. Separate memory from ledger

Use this rule:

- Memory answers "what should I remember?"
- Ledger answers "what happened, in what order, and why do I believe it?"

If the surface cannot answer the second question, it is not yet a durable ledger.

#### 4. Determine compression readiness

Set `compression_ready` to:
- `yes` when the substrate is durable, chronological, and readable now
- `partial` when the substrate exists but needs one repair step or wrapper
- `no` when there is nothing reliable to compress from

Typical `repairable` examples:
- `CIL.md` exists but the isnad path is missing
- append-only chains exist but no stable convention identifies active vs superseded records
- harness transcript exists but needs export into a repo-local append-only format before safe compaction

## Durable Ledger Quick Reference

| Signal | Weight | Meaning |
|-------|--------|---------|
| `.isnad/ledger.jsonl` plus append-only contract | High | Durable ledger present |
| isnad chains with append-only history | High | Durable ledger present |
| `CIL.md` with valid source chains | Medium | Strong evidence for an underlying ledger |
| replayable harness transcript with stable ids | Medium | May be enough if chronology and access are real |
| mutable harness memory notes | Low | Useful memory surface, not sufficient ledger by itself |
| summary file with no source history | Low | Derived state only |

## Durable Ledger Reference

See [references/durable-ledger-signals.md](references/durable-ledger-signals.md) for the signal matrix and a verified example.

## Durable Ledger Common Mistakes

| Mistake | Better move |
|--------|-------------|
| Treating any persistent memory as a ledger | Check chronology, replay, and auditability explicitly |
| Treating `CIL.md` as the ledger | Follow `cil_paths` or `src` back to the source chains |
| Treating a summary file as sufficient for compression | Require source history, not just current state |
| Calling mutable notes durable because they survive resets | Ask whether silent overwrite destroys provenance |
| Ignoring repo-local append-only logs because the harness has memory | Prefer the inspectable ledger under your control |

## Durable Ledger Worked Result Pattern

For a repo with no local ledger but some harness memory, say so plainly:

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
- the current harness exposes persistent memory notes, but those notes are mutable rather than append-only
gaps:
- no chronological append-only evidence plane
- no repo-local source history for future compression
notes: memory is available as a support surface, but a durable ledger still needs to be created
```
