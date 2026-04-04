#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any


def plugin_root() -> Path:
    # scripts/install_hooks.py -> scripts -> skill -> skills -> plugin root
    return Path(__file__).resolve().parents[3]


def hook_command(root: Path) -> str:
    script_path = root / "scripts" / "codex_durable_ledger.py"
    return f"python3 {shlex.quote(str(script_path))}"


def desired_hooks(root: Path) -> dict[str, Any]:
    command = hook_command(root)
    return {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|resume",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command,
                        }
                    ],
                }
            ],
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": command,
                        }
                    ]
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": command,
                        }
                    ]
                }
            ],
        }
    }


MANAGED_HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def hook_entry_key(group: dict[str, Any]) -> tuple[str | None, str]:
    matcher = group.get("matcher")
    hooks = group.get("hooks") or []
    command = ""
    if isinstance(hooks, list) and hooks:
        first = hooks[0]
        if isinstance(first, dict):
            command = str(first.get("command", ""))
    return (matcher, command)


def merge_hooks(existing: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
    merged = existing if isinstance(existing, dict) else {}
    merged_hooks = merged.get("hooks")
    if not isinstance(merged_hooks, dict):
        merged_hooks = {}

    for event_name in MANAGED_HOOK_EVENTS:
        merged_hooks.pop(event_name, None)

    for event_name, desired_groups in desired["hooks"].items():
        merged_hooks[event_name] = desired_groups

    merged["hooks"] = merged_hooks
    return merged


def backup_path(target: Path) -> Path:
    return target.with_name(f"{target.name}.bak")


def write_atomic(target: Path, contents: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_text(contents)
    tmp.replace(target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install durable-ledger Codex hooks.")
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.home() / ".codex" / "hooks.json",
        help="Hooks file to write or merge (default: ~/.codex/hooks.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the merged hooks JSON without writing anything",
    )
    args = parser.parse_args()

    root = plugin_root()
    desired = desired_hooks(root)
    target: Path = args.target.expanduser()

    existing: dict[str, Any] = {}
    if target.exists():
        try:
            existing = load_json(target)
        except Exception as exc:  # noqa: BLE001
            print(f"warning: failed to parse existing hooks file {target}: {exc}", file=sys.stderr)
            existing = {}

    merged = merge_hooks(existing, desired)
    rendered = json.dumps(merged, indent=2, sort_keys=True) + "\n"

    if args.dry_run:
        print(rendered, end="")
        return 0

    if target.exists():
        backup = backup_path(target)
        if not backup.exists():
            shutil.copy2(target, backup)

    write_atomic(target, rendered)
    print(f"installed durable-ledger hooks at {target}")
    print(f"hook commands point at {root / 'scripts' / 'codex_durable_ledger.py'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
