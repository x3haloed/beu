# Harness Signals

This reference supports [../SKILL.md](../SKILL.md) with concrete signals and one verified example.

## Signal Matrix

| Harness guess | High-confidence signals | Supporting signals | Weak signals |
|--------------|-------------------------|--------------------|--------------|
| OpenClaw | Active instructions explicitly name OpenClaw; live tool surface or runtime contract is OpenClaw-specific | `~/.openclaw/workspace/AGENTS.md`, `IDENTITY.md`, `TOOLS.md`, `openclaw.json` | `~/.openclaw` by itself |
| GitHub Copilot | Active instructions identify the agent as GitHub Copilot | `.github/copilot-instructions.md`, VS Code tool surface, editor context in VS Code | `~/.copilot` |
| Claude Code | Active instructions identify Claude Code or Claude-specific skill loading | `CLAUDE.md`, `~/.claude/skills`, Claude-specific docs or commands | `~/.claude` |
| Cursor | Active instructions or tool surface identify Cursor | `.cursorrules`, VS Code-family host clues | `~/.cursor` |
| Codex | Active instructions identify Codex, or Codex-only environment contract is present | `AGENTS.md`, `CODEX_CI`, Codex CLI assumptions | `~/.agents` |
| Custom | Live tool surface or session contract is clearly active but does not match any known harness | Repo-local bootstrap files or custom startup docs | Any home directory or generic provider metadata |

## Evidence Order

Always weight evidence in this order:

1. Explicit self-identification
2. Live tool surface
3. Repo bootstrap files
4. Environment variables
5. Home-directory traces

Decision rules:
- One high-confidence signal is decisive.
- Two medium-confidence signals that agree are sufficient when no high-confidence signal exists.
- Low-confidence signals never decide the harness on their own.
- Conflicting signals at comparable weight should return `ambiguous`.
- Explicit self-identification overrides weaker signals unless another equally explicit signal disagrees.

## Important Distinctions

### Editor host is not the same as harness

`TERM_PROGRAM=vscode` means the live host is a VS Code-family editor. It does not distinguish GitHub Copilot from Cursor by itself.

### Provider/model metadata is not harness identity

`Provider: openai-codex` can describe the backend model/service for a session without meaning the current harness is Codex. Check the live instructions and tool surface first.

### Bootstrap files are supporting evidence, not proof

A repo can contain multiple harness-related files over time. Presence alone does not prove the active harness unless it matches the repo's expected bootstrap surface.

### Installation traces are not runtime identity

It is common for multiple harness directories to exist on one machine.

Example:

```text
/Users/chad/.openclaw
/Users/chad/.claude
/Users/chad/.copilot
/Users/chad/.cursor
```

This proves only that those tools have been used or installed before.

### Shared machine state is not shared agent identity

Logs, transcripts, and coordination notes can mention other agents or harnesses. Those artifacts are context, not proof of the current session's harness. Resolve identity from the current runtime first.

## Verified Example: Current Session

Observed facts:
- The active instructions identify the agent as GitHub Copilot.
- The live tool surface includes VS Code editor integration primitives.
- `TERM_PROGRAM=vscode` is present.
- `~/.openclaw`, `~/.claude`, `~/.copilot`, and `~/.cursor` can all exist on the same machine, so home-directory presence is non-decisive.

Resolved result:

```text
harness_id: github-copilot
host_editor: vscode
confidence: high
evidence:
- active instructions identify the agent as GitHub Copilot
- live tool surface includes VS Code editor integration tools
- TERM_PROGRAM=vscode confirms the editor host family
bootstrap_surface: .github/copilot-instructions.md
conflicts:
- none
notes: local harness directories coexist, so file-system traces are weak evidence only
```

## Ambiguous Example

Observed facts:
- The repo contains `AGENTS.md`.
- The live tool surface is strongly VS Code-specific.
- The active instructions explicitly identify GitHub Copilot.

Resolved result:

```text
harness_id: github-copilot
host_editor: vscode
confidence: high
evidence:
- active instructions identify the agent as GitHub Copilot
- live tool surface matches a VS Code-hosted Copilot session
- `AGENTS.md` is present as supporting repo state only
bootstrap_surface: .github/copilot-instructions.md
conflicts:
- repo bootstrap file suggests a Codex-compatible fallback, but explicit runtime identity is GitHub Copilot
notes: stronger runtime evidence wins over weaker repo-file evidence
```

If instead two comparable high-confidence signals disagreed, return:

```text
harness_id: ambiguous
host_editor: unknown
confidence: low
evidence:
- active runtime exposes one harness-specific tool surface
- active instructions explicitly name a different harness
bootstrap_surface: unknown
conflicts:
- explicit self-identification and live tool surface disagree at similar weight
notes: do not guess; gather another runtime-specific probe
```

## Minimum Reliable Algorithm

1. Check the active instructions for explicit harness naming.
2. Check whether the live tool surface matches a known harness or host family.
3. Use bootstrap-file conventions as supporting evidence only.
4. Use environment variables to resolve editor host, not to overclaim harness identity.
5. Ignore home-directory traces unless all stronger signals are missing.
6. If two comparable stronger signals disagree, return `ambiguous`.
