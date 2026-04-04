#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_EVENT_CHUNK_SIZE = 10
DEFAULT_CODEX_HOME_DIR = Path("/tmp/codex-home")
DEFAULT_CODEX_WORK_DIR_NAME = "work"
DEFAULT_CODEX_AUTH_SOURCE = Path("/Users/chad/.codex/auth.json")
WAKE_PACK_OPEN_TAG = "<wake_pack>"
WAKE_PACK_CLOSE_TAG = "</wake_pack>"
DEFAULT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "wake_pack": {
            "type": "string",
        }
    },
    "required": ["wake_pack"],
    "additionalProperties": False,
}


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


def _write_temp_json(data: dict[str, Any], directory: Path, filename: str) -> Path:
    path = directory / filename
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _toml_basic_string(value: str) -> str:
    return json.dumps(value)


def _ensure_codex_home(codex_home_dir: Path, *, model: str | None) -> Path:
    codex_home_dir.mkdir(parents=True, exist_ok=True)
    config_path = codex_home_dir / "config.toml"
    if not config_path.exists() or config_path.read_text(encoding="utf-8").strip() == "":
        default_model = model or "gpt-5.4-mini"
        config_path.write_text(
            "# Isolated Codex home for scheduled compressor runs.\n"
            f"model = {_toml_basic_string(default_model)}\n",
            encoding="utf-8",
        )
    work_dir = codex_home_dir / DEFAULT_CODEX_WORK_DIR_NAME
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _ensure_symlink(source: Path, target: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Missing required source file: {source}")
    if target.is_symlink():
        if target.resolve() == source.resolve():
            return
        target.unlink()
    elif target.exists():
        target.unlink()
    target.symlink_to(source)


def _run_codex(
    codex_command: str,
    prompt_text: str,
    cwd: Path,
    *,
    model: str | None,
    output_schema_path: Path,
    last_message_path: Path,
    codex_home_dir: Path,
) -> subprocess.CompletedProcess[str]:
    command = [
        codex_command,
        "exec",
        "--full-auto",
        "--skip-git-repo-check",
        "--output-schema",
        str(output_schema_path),
        "--output-last-message",
        str(last_message_path),
        "--cd",
        str(cwd),
        "-",
    ]
    if model:
        command[1:1] = ["-m", model]
    return subprocess.run(
        command,
        input=prompt_text,
        cwd=str(cwd),
        env={**os.environ, "CODEX_HOME": str(codex_home_dir)},
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
        if isinstance(wake_pack, str):
            return wake_pack + "\n", parsed
    return text + "\n", parsed if isinstance(parsed, dict) else None


def _wrap_wake_pack(wake_pack: str) -> str:
    text = wake_pack.strip()
    if text.startswith(WAKE_PACK_OPEN_TAG) and text.endswith(WAKE_PACK_CLOSE_TAG):
        return text + "\n"
    if text:
        return f"{WAKE_PACK_OPEN_TAG}\n{text}\n{WAKE_PACK_CLOSE_TAG}\n"
    return f"{WAKE_PACK_OPEN_TAG}\n{WAKE_PACK_CLOSE_TAG}\n"


def _read_final_message(last_message_path: Path, fallback_stdout: str) -> str:
    if last_message_path.is_file():
        try:
            text = last_message_path.read_text(encoding="utf-8").strip()
        except Exception:
            text = ""
        if text:
            return text
    text = fallback_stdout.strip()
    if text:
        return text
    raise ValueError("Codex did not produce a final message")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Codex compressor and refresh the wake pack")
    parser.add_argument("--config", required=True, help="Path to the installed compressor config JSON")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    config = _load_config(config_path)

    home_dir = Path(str(config["homeDir"])).expanduser().resolve()
    codex_home_dir = Path(str(config.get("codexHomeDir") or DEFAULT_CODEX_HOME_DIR)).expanduser().resolve()
    codex_work_dir = Path(
        str(config.get("codexWorkDir") or (codex_home_dir / DEFAULT_CODEX_WORK_DIR_NAME))
    ).expanduser().resolve()
    prompt_path = Path(str(config["promptPath"])).expanduser().resolve()
    output_path = Path(str(config["outputPath"])).expanduser().resolve()
    log_path = Path(str(config["logPath"])).expanduser().resolve()
    state_path = Path(str(config["statePath"])).expanduser().resolve()
    history_path = Path(str(config["wakePackHistoryPath"])).expanduser().resolve()
    ledger_events_path = Path(str(config["ledgerEventsPath"])).expanduser().resolve()
    event_chunk_size = int(config.get("eventChunkSize") or DEFAULT_EVENT_CHUNK_SIZE)
    codex_command = shutil.which(str(config.get("codexCommand") or "codex")) or str(
        config.get("codexCommand") or "codex"
    )
    codex_model = str(config.get("codexModel") or "").strip() or None
    codex_auth_source = Path(str(config.get("codexAuthSource") or DEFAULT_CODEX_AUTH_SOURCE)).expanduser().resolve()
    codex_auth_target = codex_home_dir / "auth.json"

    state = _load_state(state_path)
    all_events = _iter_jsonl(ledger_events_path)
    start_index = max(0, int(state.get("last_processed_event_index") or 0))
    remaining_events = all_events[start_index:]

    record = {
        "ran_at": _now(),
        "home_dir": str(home_dir),
        "codex_home_dir": str(codex_home_dir),
        "codex_work_dir": str(codex_work_dir),
        "codex_auth_source": str(codex_auth_source),
        "codex_auth_target": str(codex_auth_target),
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

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        output_schema_path = _write_temp_json(DEFAULT_OUTPUT_SCHEMA, temp_dir_path, "output-schema.json")
        last_message_path = temp_dir_path / "last-message.json"
        codex_work_dir = _ensure_codex_home(codex_home_dir, model=codex_model)
        _ensure_symlink(codex_auth_source, codex_auth_target)
        result = _run_codex(
            codex_command,
            prompt_text,
            codex_work_dir,
            model=codex_model,
            output_schema_path=output_schema_path,
            last_message_path=last_message_path,
            codex_home_dir=codex_home_dir,
        )
        record.update({"returncode": result.returncode, "stderr": result.stderr.strip()})

        if result.returncode != 0:
            _append_log(log_path, {**record, "status": "codex_error"})
            return result.returncode

        final_message = _read_final_message(last_message_path, result.stdout)
        wake_pack_text, parsed_output = _extract_wake_pack(final_message)
        wrapped_wake_pack = _wrap_wake_pack(wake_pack_text)
        processed_end_index = start_index + len(event_chunk)
        history_record = {
            "ran_at": _now(),
            "event_index_start": start_index,
            "event_index_end": processed_end_index,
            "event_count": len(event_chunk),
            "wake_pack": wrapped_wake_pack.rstrip("\n"),
            "source_event_ids": [record.get("id") for record in event_chunk if isinstance(record.get("id"), str)],
            "compressor_output": parsed_output,
        }
        _atomic_write(output_path, wrapped_wake_pack)
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
