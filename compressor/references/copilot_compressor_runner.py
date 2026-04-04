#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_EVENT_CHUNK_SIZE = 10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_config(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Invalid config file: {path}")
    return loaded


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _run_copilot(copilot_command: str, prompt_text: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    command = [copilot_command, "-p", prompt_text, "--silent"]
    return subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _append_log(log_path: Path, record: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True))
        handle.write("\n")


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                loaded = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(loaded, dict):
                records.append(loaded)
    return records


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"last_processed_event_index": 0}
    loaded = _load_config(path)
    if "last_processed_event_index" not in loaded:
        loaded["last_processed_event_index"] = 0
    return loaded


def _latest_wake_pack(history_path: Path) -> str:
    latest = ""
    for record in _iter_jsonl(history_path):
        wake_pack = record.get("wake_pack")
        if isinstance(wake_pack, str):
            latest = wake_pack
    return latest


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True))
        handle.write("\n")


def _build_prompt(template: str, previous_wake_pack: str, event_chunk: list[dict[str, Any]]) -> str:
    rendered_events = "\n".join(json.dumps(event, ensure_ascii=True, sort_keys=True) for event in event_chunk)
    wake_pack_block = previous_wake_pack.strip() or "<empty>"
    return (
        f"{template.rstrip()}\n\n"
        "PREVIOUS_WAKE_PACK\n"
        f"{wake_pack_block}\n\n"
        "UNPROCESSED_LEDGER_EVENTS_JSONL\n"
        f"{rendered_events}\n\n"
        "Return only JSON matching the OUTPUT schema.\n"
    )


def _extract_wake_pack(output_text: str) -> tuple[str, dict[str, Any] | None]:
    text = output_text.strip()
    if not text:
        raise ValueError("Compressor returned empty output")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text, None
    if isinstance(parsed, dict):
        wake_pack = parsed.get("wake_pack")
        if isinstance(wake_pack, str) and wake_pack.strip():
            return wake_pack.strip() + "\n", parsed
    return text + "\n", parsed if isinstance(parsed, dict) else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Copilot compressor and refresh copilot-instructions.md")
    parser.add_argument("--config", required=True, help="Path to the installed compressor config JSON")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    config = _load_config(config_path)

    home_dir = Path(str(config["homeDir"])).expanduser().resolve()
    prompt_path = Path(str(config["promptPath"])).expanduser().resolve()
    output_path = Path(str(config["outputPath"])).expanduser().resolve()
    log_path = Path(str(config["logPath"])).expanduser().resolve()
    state_path = Path(str(config["statePath"])).expanduser().resolve()
    history_path = Path(str(config["wakePackHistoryPath"])).expanduser().resolve()
    ledger_events_path = Path(str(config["ledgerEventsPath"])).expanduser().resolve()
    event_chunk_size = int(config.get("eventChunkSize") or DEFAULT_EVENT_CHUNK_SIZE)
    copilot_command = shutil.which(str(config.get("copilotCommand") or "copilot")) or str(
        config.get("copilotCommand") or "copilot"
    )

    state = _load_state(state_path)
    all_events = _iter_jsonl(ledger_events_path)
    start_index = max(0, int(state.get("last_processed_event_index") or 0))
    remaining_events = all_events[start_index:]

    record = {
        "ran_at": _now(),
        "home_dir": str(home_dir),
        "output_path": str(output_path),
        "ledger_events_path": str(ledger_events_path),
        "last_processed_event_index": start_index,
        "unprocessed_event_count": len(remaining_events),
    }

    if not remaining_events:
        _append_log(log_path, {**record, "status": "no_unprocessed_events"})
        return 0

    event_chunk = remaining_events[:event_chunk_size]
    template = prompt_path.read_text(encoding="utf-8")
    previous_wake_pack = _latest_wake_pack(history_path)
    prompt_text = _build_prompt(template, previous_wake_pack, event_chunk)
    result = _run_copilot(copilot_command, prompt_text, home_dir)
    record.update({"returncode": result.returncode, "stderr": result.stderr.strip()})

    if result.returncode != 0:
        _append_log(log_path, {**record, "status": "copilot_error"})
        return result.returncode

    wake_pack_text, parsed_output = _extract_wake_pack(result.stdout)
    processed_end_index = start_index + len(event_chunk)
    history_record = {
        "ran_at": _now(),
        "event_index_start": start_index,
        "event_index_end": processed_end_index,
        "event_count": len(event_chunk),
        "wake_pack": wake_pack_text.rstrip("\n"),
        "source_event_ids": [record.get("id") for record in event_chunk if isinstance(record.get("id"), str)],
        "compressor_output": parsed_output,
    }
    _atomic_write(output_path, wake_pack_text)
    _append_jsonl(history_path, history_record)
    _atomic_write(
        state_path,
        json.dumps({"last_processed_event_index": processed_end_index, "updated_at": _now()}, ensure_ascii=True, indent=2)
        + "\n",
    )
    _append_log(
        log_path,
        {
            **record,
            "status": "updated",
            "stdout_bytes": len(result.stdout.encode("utf-8")),
            "processed_event_count": len(event_chunk),
            "processed_end_index": processed_end_index,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
