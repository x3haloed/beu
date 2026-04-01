# Harness Signals

This reference supports [../SKILL.md](../SKILL.md) with concrete signals and one verified example.

## Signal Matrix

| Harness guess | High-confidence signals | Supporting signals | Weak signals |
|--------------|-------------------------|--------------------|--------------|
| Hermes | `hermes chat` launch line, Hermes-native tool surface, active developer instructions naming Hermes | `~/.hermes`, Hermes CLI metadata | `Provider: openai-codex` by itself |
| GitHub Copilot | Active instructions identify the agent as GitHub Copilot | `.github/copilot-instructions.md`, VS Code tool surface, editor context in VS Code | `~/.copilot` |
| Claude Code | Active instructions identify Claude Code or Claude-specific skill loading | `CLAUDE.md`, `~/.claude/skills`, Claude-specific docs or commands | `~/.claude` |
| Cursor | Active instructions or tool surface identify Cursor | `.cursorrules`, VS Code-family host clues | `~/.cursor` |
| Codex | Active instructions identify Codex, or Codex-only environment contract is present | `AGENTS.md`, `CODEX_CI`, Codex CLI assumptions | `~/.agents` |

## Important Distinctions

### Editor host is not the same as harness

`TERM_PROGRAM=vscode` means the live host is a VS Code-family editor. It does not distinguish GitHub Copilot from Cursor by itself.

### Provider/model metadata is not harness identity

`Provider: openai-codex` can describe the backend model/service for a session without meaning the current harness is Codex. Check the live launch line and tool surface first.

### Bootstrap files are supporting evidence, not proof

A repo can contain multiple harness-related files over time. Presence alone does not prove the active harness unless it matches the repo's expected bootstrap surface.

### Installation traces are not runtime identity

It is common for multiple harness directories to exist on one machine.

Example:

```text
/Users/chad/.claude
/Users/chad/.copilot
/Users/chad/.cursor
```

This proves only that those tools have been used or installed before.

## Verified Example: Current Session

Observed facts:
- The active instructions identify the agent as GitHub Copilot.
- The live tool surface includes VS Code editor integration primitives.
- `TERM_PROGRAM=vscode` is present.
- `~/.claude`, `~/.copilot`, and `~/.cursor` all exist, so home-directory presence is non-decisive.

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
notes: local harness directories coexist, so file-system traces are weak evidence only
```

## Minimum Reliable Algorithm

1. Check the active instructions for explicit harness naming.
2. Check whether the tool surface matches a known host family.
3. Use bootstrap-file conventions as supporting evidence.
4. Use environment variables to resolve editor host, not to overclaim harness identity.
5. Ignore home-directory traces unless all stronger signals are missing.
6. If two stronger signals disagree, return `ambiguous`.