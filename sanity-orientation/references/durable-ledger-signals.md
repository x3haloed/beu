# Durable Ledger Signals

This reference supports [../SKILL.md](../SKILL.md) with concrete detection rules for the second primitive.

## Durable Ledger Standard

A surface counts as a durable ledger only if it is:
- persistent across session resets
- readable by a future agent instance
- chronological or append-ordered
- auditable when corrected
- useful as source material for later compression

If a surface is persistent but silently mutable, it is memory support, not a full ledger.

## Signal Matrix

| Candidate surface | Strength | Why |
|------------------|----------|-----|
| `.isnad/ledger.jsonl` plus `.isnad/control.jsonl` | High | Explicit append-only evidence and control planes |
| isnad chain directory with append-only markdown files | High | Durable chronological provenance substrate |
| repo-local custom append-only log with record ids | High | Satisfies chronology and auditability if corrections are additive |
| `CIL.md` plus valid source chains | Medium | Strong sign of a real ledger behind compiled state |
| harness transcript/history with stable ids and replay | Medium | Can qualify if future sessions can re-read it reliably |
| persistent harness memory notes | Low | Helpful continuity surface, but usually mutable |
| `STATE.md`, `WAKE.md`, `CIL.md` without source history | Low | Derived state only |
| git commits alone | Low | Code history is not the same as agent causal history |

## False Positives

These often look promising but are not enough by themselves:

- `CIL.md` without isnads or another source ledger
- repo bootstrap files such as `AGENTS.md` or `.github/copilot-instructions.md`
- a vector store or embedding index without source records
- editable memory notes with no append-only discipline
- a current-session transcript that cannot be re-read on the next wake

## Decision Rules

1. Prefer repo-local append-only structures over harness-managed opaque memory.
2. If compiled state exists, trace it back to source before calling the ledger present.
3. If the harness offers durable replayable transcripts with stable ids, classify that carefully and note any auditability gap.
4. If only mutable memory exists, report `absent` or `repairable`, not `present`.
5. If you cannot verify persistence or chronology, report `ambiguous`.

## Classification Guide

### `present`

Use when the ledger already exists and can be compressed from now.

Examples:
- `.isnad/ledger.jsonl` and `.isnad/control.jsonl` are present.
- `CIL.md` exists and points to an intact `isnads/` directory.
- a custom append-only log already records actions, evidence, and corrections.

### `repairable`

Use when the substrate exists but one missing piece blocks safe use.

Examples:
- `CIL.md` exists but `cil_paths` points to a missing chain directory.
- chains exist but there is no clear supersession convention.
- the harness transcript is durable but should be exported into a repo-local append-only format before compaction.

### `absent`

Use when no chronological durable substrate exists.

Examples:
- only bootstrap files and skills are present
- only mutable harness memory exists
- only current summaries exist

### `ambiguous`

Use when there are hints of persistence, but you cannot verify replay or order.

Examples:
- the harness claims to save history, but the agent cannot inspect it
- a custom directory exists, but its files do not show whether history is append-only or replace-in-place

## Verified Example: Current BeU Rewrite Repo

Observed facts:
- The repo contains only the skill scaffolding and no `.isnad/` workspace.
- No `CIL.md`, `ledger.jsonl`, `control.jsonl`, `isnads/`, or `chains/` paths were found.
- The current harness exposes persistent memory scopes, but that surface is a mutable note system rather than an append-only provenance log.

Resolved result:

```text
ledger_status: absent
ledger_kind: none
durability: low
compression_ready: no
paths_or_surface:
- harness memory scopes only
evidence:
- no repo-local append-only ledger files were found
- no compiled CIL surface or backing chains were found
- available harness memory is mutable and does not itself prove chronology or auditability
gaps:
- no evidence plane
- no source history for a compressor to consume
notes: the harness memory can support continuity, but a repo-local ledger still needs to be established
```