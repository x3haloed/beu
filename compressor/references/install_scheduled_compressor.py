#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


PROMPT_FILE_NAME = "compressor-prompt.txt"
RUNNER_FILE_BY_BACKEND = {
    "copilot": "copilot_compressor_runner.py",
    "codex": "codex_compressor_runner.py",
}
CONFIG_FILE_BY_BACKEND = {
    "copilot": "copilot-compressor.json",
    "codex": "codex-compressor.json",
}
LOG_FILE_BY_BACKEND = {
    "copilot": "copilot-compressor.log",
    "codex": "codex-compressor.log",
}
STATE_FILE_BY_BACKEND = {
    "copilot": "copilot-compressor-state.json",
    "codex": "codex-compressor-state.json",
}
WAKE_PACK_HISTORY_FILE_BY_BACKEND = {
    "copilot": "wake-pack-history.jsonl",
    "codex": "wake-pack-history.jsonl",
}


def _slugify(path: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(path).lower()).strip("-") or "copilot-compressor"


def _detect_scheduler() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "launchd"
    if system == "windows":
        return "schtasks"
    return "cron"


def _detect_backend(invocation_name: str, explicit_backend: str | None, *, source_dir: Path) -> str:
    if explicit_backend and explicit_backend != "auto":
        return explicit_backend
    lowered = invocation_name.lower()
    if "codex" in lowered:
        return "codex"
    if "copilot" in lowered:
        return "copilot"
    if (source_dir / RUNNER_FILE_BY_BACKEND["codex"]).is_file():
        return "codex"
    if (source_dir / RUNNER_FILE_BY_BACKEND["copilot"]).is_file():
        return "copilot"
    raise FileNotFoundError("Could not infer backend; missing both codex and copilot runner files")


def _run(command: list[str], *, dry_run: bool) -> None:
    if dry_run:
        print("DRY RUN:", " ".join(command))
        return
    subprocess.run(command, check=False)


def _write_file(path: Path, content: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"DRY RUN: write {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy_file(source: Path, target: Path, *, dry_run: bool) -> None:
    if dry_run:
        print(f"DRY RUN: copy {source} -> {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _remove_path(path: Path, *, dry_run: bool) -> None:
    if not path.exists():
        return
    if dry_run:
        print(f"DRY RUN: remove {path}")
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _install_launchd(
    *,
    label: str,
    python_path: str,
    runner_path: Path,
    config_path: Path,
    working_dir: Path,
    log_path: Path,
    interval_minutes: int,
    dry_run: bool,
) -> None:
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path)], dry_run=dry_run)
    _remove_path(plist_path, dry_run=dry_run)
    plist = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
  <key>Label</key>
  <string>{escape(label)}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{escape(python_path)}</string>
    <string>{escape(str(runner_path))}</string>
    <string>--config</string>
    <string>{escape(str(config_path))}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>{escape(str(working_dir))}</string>
  <key>StartInterval</key>
  <integer>{interval_minutes * 60}</integer>
  <key>StandardOutPath</key>
  <string>{escape(str(log_path))}</string>
  <key>StandardErrorPath</key>
  <string>{escape(str(log_path))}</string>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
"""
    _write_file(plist_path, plist, dry_run=dry_run)
    _run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)], dry_run=dry_run)
    _run(["launchctl", "enable", f"gui/{os.getuid()}/{label}"], dry_run=dry_run)


def _install_cron(
    *,
    marker: str,
    python_path: str,
    runner_path: Path,
    config_path: Path,
    working_dir: Path,
    log_path: Path,
    interval_minutes: int,
    dry_run: bool,
) -> None:
    if interval_minutes < 1 or interval_minutes > 59:
        raise ValueError("cron mode supports interval minutes in the range 1-59")
    begin = f"# BEGIN {marker}"
    end = f"# END {marker}"
    cron_line = (
        f"*/{interval_minutes} * * * * cd {shlex_quote(str(working_dir))} && "
        f"{shlex_quote(python_path)} {shlex_quote(str(runner_path))} --config {shlex_quote(str(config_path))} "
        f">> {shlex_quote(str(log_path))} 2>&1"
    )
    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    current = existing.stdout if existing.returncode == 0 else ""
    lines = current.splitlines()
    filtered: list[str] = []
    in_block = False
    for line in lines:
        if line.strip() == begin:
            in_block = True
            continue
        if line.strip() == end:
            in_block = False
            continue
        if not in_block:
            filtered.append(line)
    filtered.extend([begin, cron_line, end])
    new_content = "\n".join(filtered).strip() + "\n"
    if dry_run:
        print("DRY RUN: install crontab block")
        print(new_content)
        return
    subprocess.run(["crontab", "-"], input=new_content, text=True, check=True)


def _install_schtasks(
    *,
    task_name: str,
    python_path: str,
    runner_path: Path,
    config_path: Path,
    interval_minutes: int,
    dry_run: bool,
) -> None:
    _run(["schtasks", "/Delete", "/TN", task_name, "/F"], dry_run=dry_run)
    task_command = f'"{python_path}" "{runner_path}" --config "{config_path}"'
    _run(
        [
            "schtasks",
            "/Create",
            "/SC",
            "MINUTE",
            "/MO",
            str(interval_minutes),
            "/TN",
            task_name,
            "/TR",
            task_command,
            "/F",
        ],
        dry_run=dry_run,
    )


def shlex_quote(value: str) -> str:
    return subprocess.list2cmdline([value]) if platform.system().lower() == "windows" else __import__("shlex").quote(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install a scheduled compressor job with backend-specific isolation")
    parser.add_argument(
        "--home-dir",
        required=True,
        help="Stable home directory where the published compressor output should live",
    )
    parser.add_argument(
        "--ledger-namespace-dir",
        required=True,
        help="Path to the durable-ledger namespace directory containing events.jsonl",
    )
    parser.add_argument("--interval-minutes", type=int, default=15, help="How often to run the compressor")
    parser.add_argument("--event-chunk-size", type=int, default=10, help="How many ledger events to process per run")
    parser.add_argument(
        "--backend",
        choices=("auto", "codex", "copilot"),
        default="auto",
        help="Which compressor backend to install",
    )
    parser.add_argument(
        "--scheduler",
        choices=("auto", "launchd", "cron", "schtasks"),
        default="auto",
        help="Scheduler backend to install",
    )
    parser.add_argument("--codex-command", default="codex", help="Codex executable to invoke from the runner")
    parser.add_argument("--codex-model", default="gpt-5.4-mini", help="Codex model to use for compression runs")
    parser.add_argument(
        "--codex-home-dir",
        default="/tmp/codex-home",
        help="Isolated Codex home used only for scheduled Codex compressor runs",
    )
    parser.add_argument(
        "--codex-auth-source",
        default="/Users/chad/.codex/auth.json",
        help="Codex auth file to symlink into the isolated home before codex exec starts",
    )
    parser.add_argument("--copilot-command", default="copilot", help="Copilot executable to invoke from the runner")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without modifying the system")
    args = parser.parse_args()

    scheduler = _detect_scheduler() if args.scheduler == "auto" else args.scheduler
    source_dir = Path(__file__).resolve().parent
    backend = _detect_backend(Path(sys.argv[0]).name, args.backend, source_dir=source_dir)
    home_dir = Path(args.home_dir).expanduser().resolve()
    install_dir = home_dir / ".beu" / "compressor"
    ledger_namespace_dir = Path(args.ledger_namespace_dir).expanduser().resolve()
    prompt_target = install_dir / PROMPT_FILE_NAME
    runner_file_name = RUNNER_FILE_BY_BACKEND[backend]
    config_file_name = CONFIG_FILE_BY_BACKEND[backend]
    log_file_name = LOG_FILE_BY_BACKEND[backend]
    state_file_name = STATE_FILE_BY_BACKEND[backend]
    history_file_name = WAKE_PACK_HISTORY_FILE_BY_BACKEND[backend]
    runner_target = install_dir / runner_file_name
    config_target = install_dir / config_file_name
    log_path = install_dir / log_file_name
    state_path = install_dir / state_file_name
    wake_pack_history_path = install_dir / history_file_name
    instructions_path = (
        ledger_namespace_dir / "wake-pack.md"
        if backend == "codex"
        else home_dir / ".github" / "copilot-instructions.md"
    )
    codex_home_dir = Path(args.codex_home_dir).expanduser().resolve()
    codex_work_dir = codex_home_dir / "work"
    codex_auth_source = Path(args.codex_auth_source).expanduser().resolve()
    source_prompt = source_dir / PROMPT_FILE_NAME
    source_runner = source_dir / runner_file_name

    if not source_prompt.is_file():
        raise FileNotFoundError(f"Missing prompt file: {source_prompt}")
    if not source_runner.is_file():
        raise FileNotFoundError(f"Missing runner file: {source_runner}")
    if not (ledger_namespace_dir / "events.jsonl").is_file():
        raise FileNotFoundError(f"Missing events.jsonl under ledger namespace dir: {ledger_namespace_dir}")

    python_path = shutil.which("python3") or sys.executable
    slug = _slugify(home_dir)
    label = f"com.beu.{backend}-compressor.{slug}"

    config = {
        "backend": backend,
        "homeDir": str(home_dir),
        "ledgerNamespaceDir": str(ledger_namespace_dir),
        "ledgerEventsPath": str(ledger_namespace_dir / "events.jsonl"),
        "promptPath": str(prompt_target),
        "outputPath": str(instructions_path),
        "logPath": str(log_path),
        "statePath": str(state_path),
        "wakePackHistoryPath": str(wake_pack_history_path),
        "eventChunkSize": args.event_chunk_size,
        "codexHomeDir": str(codex_home_dir),
        "codexWorkDir": str(codex_work_dir),
        "codexAuthSource": str(codex_auth_source),
        ("codexCommand" if backend == "codex" else "copilotCommand"): (
            args.codex_command if backend == "codex" else args.copilot_command
        ),
    }
    if backend == "codex":
        config["codexModel"] = args.codex_model

    _copy_file(source_prompt, prompt_target, dry_run=args.dry_run)
    _copy_file(source_runner, runner_target, dry_run=args.dry_run)
    _write_file(config_target, json.dumps(config, indent=2) + "\n", dry_run=args.dry_run)

    if scheduler == "launchd":
        _install_launchd(
            label=label,
            python_path=python_path,
            runner_path=runner_target,
            config_path=config_target,
            working_dir=home_dir,
            log_path=log_path,
            interval_minutes=args.interval_minutes,
            dry_run=args.dry_run,
        )
    elif scheduler == "cron":
        _install_cron(
            marker=label,
            python_path=python_path,
            runner_path=runner_target,
            config_path=config_target,
            working_dir=home_dir,
            log_path=log_path,
            interval_minutes=args.interval_minutes,
            dry_run=args.dry_run,
        )
    elif scheduler == "schtasks":
        _install_schtasks(
            task_name=label,
            python_path=python_path,
            runner_path=runner_target,
            config_path=config_target,
            interval_minutes=args.interval_minutes,
            dry_run=args.dry_run,
        )
    else:
        raise ValueError(f"Unsupported scheduler: {scheduler}")

    print(f"Installed {backend.capitalize()} compressor using {scheduler}")
    print(f"Stable home: {home_dir}")
    if backend == "codex":
        print(f"Isolated Codex home: {codex_home_dir}")
        print(f"Codex auth source: {codex_auth_source}")
    print(f"Ledger namespace dir: {ledger_namespace_dir}")
    print(f"Published output path: {instructions_path}")
    print(f"Runner config: {config_target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
