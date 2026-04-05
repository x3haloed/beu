#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

DEFAULT_INPUT_ROOT = Path.home() / ".codex" / "sessions"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "output" / "ledger_frames"
DEFAULT_FONT = Path("/System/Library/Fonts/Supplemental/Andale Mono.ttf")


@dataclass(frozen=True)
class LayoutConfig:
    width: int = 1280
    height: int = 1280
    cols: int = 5
    margin: int = 24
    header_h: int = 60
    footer_h: int = 22
    col_gap: int = 10
    card_gap: int = 8
    card_pad: int = 8
    header_size: int = 18
    subheader_size: int = 10
    meta_size: int = 7
    body_size: int = 7
    footer_size: int = 7
    min_width_chars: int = 22
    width_chars_scale: float = 4.6
    show_title: bool = False
    show_timestamps: bool = False
    show_stripe: bool = False


@dataclass(frozen=True)
class CardLayout:
    entry_id: str
    entry_type: str
    created_at: str
    segment_index: int
    segment_total: int
    segment_start: int
    segment_end: int
    id_lines: list[str]
    title_lines: list[str]
    body_lines: list[str]
    height: int


@dataclass(frozen=True)
class PlacedCard:
    x: int
    y: int
    width: int
    layout: CardLayout
    entry_type: str
    created_at: str


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return value if isinstance(value, dict) else {}


def _parse_json_text(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return text


def _indent_lines(text: str, indent: str = "  ") -> list[str]:
    lines = text.splitlines()
    if not lines:
        return [indent]
    return [f"{indent}{line}" for line in lines]


def _format_json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True, default=str)


def _normalize_compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _format_record_body(lines: list[str]) -> str:
    return "\n".join(lines).strip()


def wrap_text(text: str, width_chars: int) -> list[str]:
    if not text:
        return [""]
    out: list[str] = []
    for para in text.splitlines() or [""]:
        if not para.strip():
            out.append("")
            continue
        out.extend(textwrap.wrap(para, width=width_chars) or [""])
    return out


def line_height(font: ImageFont.FreeTypeFont) -> int:
    ascent, descent = font.getmetrics()
    return ascent + descent + 1


def max_card_height(cfg: LayoutConfig) -> int:
    return cfg.height - cfg.footer_h - 6 - (cfg.header_h + 10)


def load_fonts(font_path: Path, cfg: LayoutConfig) -> dict[str, ImageFont.FreeTypeFont]:
    return {
        "header": ImageFont.truetype(str(font_path), cfg.header_size),
        "subheader": ImageFont.truetype(str(font_path), cfg.subheader_size),
        "meta": ImageFont.truetype(str(font_path), cfg.meta_size),
        "body": ImageFont.truetype(str(font_path), cfg.body_size),
        "footer": ImageFont.truetype(str(font_path), cfg.footer_size),
    }


def _best_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _normalize_compact_text(value)
    if isinstance(value, list):
        pieces = [_best_text(item) for item in value]
        pieces = [piece for piece in pieces if piece]
        return "\n".join(pieces).strip()
    if isinstance(value, dict):
        for key in (
            "message",
            "text",
            "prompt",
            "content",
            "response",
            "result",
            "stdout",
            "stderr",
            "aggregated_output",
            "formatted_output",
            "output",
            "arguments",
            "input",
        ):
            if key in value:
                text = _best_text(value[key])
                if text:
                    return text
        return _format_json_value(value)
    return _normalize_compact_text(value)


def _message_text(content: Any) -> str:
    if isinstance(content, list):
        pieces: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = _normalize_compact_text(item.get("text"))
                if text:
                    pieces.append(text)
            else:
                text = _normalize_compact_text(item)
                if text:
                    pieces.append(text)
        if pieces:
            return "\n".join(pieces).strip()
    return _best_text(content)


def _response_item_to_record(
    payload: dict[str, Any],
    *,
    source_path: Path,
    line_no: int,
    current_turn_id: str,
) -> tuple[dict[str, Any] | None, str]:
    item_type = str(payload.get("type") or "")
    created_at = _normalize_compact_text(payload.get("timestamp"))
    record_source = {"kind": item_type or "response_item", "path": str(source_path), "line": line_no}

    def make_record(
        *,
        kind: str,
        role: str | None,
        name: str | None,
        text: str,
        turn_id: str,
        payload_value: Any = payload,
    ) -> dict[str, Any]:
        return {
            "id": f"{source_path.stem}-{line_no}-{kind}",
            "namespace": source_path.stem,
            "session_id": source_path.stem,
            "thread_id": source_path.stem,
            "turn_id": turn_id,
            "kind": kind,
            "role": role,
            "name": name,
            "text": text,
            "created_at": created_at,
            "source": record_source,
            "payload": payload_value,
        }

    if item_type == "message":
        role = _normalize_compact_text(payload.get("role"))
        if role == "system":
            return None, current_turn_id
        text = _message_text(payload.get("content"))
        if not text:
            return None, current_turn_id
        kind = "user_message" if role == "user" else "assistant_message"
        return make_record(kind=kind, role=role or kind.split("_", 1)[0], name=None, text=text, turn_id=current_turn_id), current_turn_id

    if item_type == "function_call":
        name = _normalize_compact_text(payload.get("name")) or "tool"
        arguments = payload.get("arguments")
        text = _best_text(_parse_json_text(arguments))
        if not text:
            text = _normalize_compact_text(arguments)
        turn_id = _normalize_compact_text(payload.get("turn_id")) or current_turn_id
        return make_record(kind="tool_call", role="tool", name=name, text=text, turn_id=turn_id), turn_id

    if item_type == "function_call_output":
        call_id = _normalize_compact_text(payload.get("call_id"))
        output = _parse_json_text(payload.get("output"))
        text = _best_text(output)
        name = "tool"
        if isinstance(output, dict):
            if _normalize_compact_text(output.get("tool")):
                name = _normalize_compact_text(output.get("tool"))
        turn_id = _normalize_compact_text(payload.get("turn_id")) or current_turn_id
        return make_record(kind="tool_result", role="tool", name=name, text=text, turn_id=turn_id, payload_value={"call_id": call_id, "output": output}), turn_id

    if item_type in {"reasoning", "ghost_snapshot"}:
        return None, current_turn_id

    text = _best_text(payload)
    if not text:
        return None, current_turn_id
    return make_record(kind="context", role="system", name=item_type or None, text=text, turn_id=current_turn_id), current_turn_id


def _event_msg_to_record(
    payload: dict[str, Any],
    *,
    source_path: Path,
    line_no: int,
    current_turn_id: str,
) -> tuple[dict[str, Any] | None, str]:
    ev_type = str(payload.get("type") or "")
    created_at = _normalize_compact_text(payload.get("timestamp"))
    record_source = {"kind": ev_type or "event_msg", "path": str(source_path), "line": line_no}

    def make_record(
        *,
        kind: str,
        role: str | None,
        name: str | None,
        text: str,
        turn_id: str,
        payload_value: Any = payload,
    ) -> dict[str, Any]:
        return {
            "id": f"{source_path.stem}-{line_no}-{kind}",
            "namespace": source_path.stem,
            "session_id": source_path.stem,
            "thread_id": source_path.stem,
            "turn_id": turn_id,
            "kind": kind,
            "role": role,
            "name": name,
            "text": text,
            "created_at": created_at,
            "source": record_source,
            "payload": payload_value,
        }

    if ev_type in {"turn_started", "task_started"}:
        return None, _normalize_compact_text(payload.get("turn_id")) or current_turn_id

    if ev_type in {"turn_complete", "task_complete"}:
        return None, _normalize_compact_text(payload.get("turn_id")) or current_turn_id

    if ev_type == "user_message":
        text = _normalize_compact_text(payload.get("message"))
        if not text:
            return None, current_turn_id
        turn_id = _normalize_compact_text(payload.get("turn_id")) or current_turn_id
        return make_record(kind="user_message", role="user", name=None, text=text, turn_id=turn_id), turn_id

    if ev_type == "agent_message":
        text = _normalize_compact_text(payload.get("message"))
        if not text:
            return None, current_turn_id
        return make_record(kind="assistant_message", role="assistant", name=None, text=text, turn_id=current_turn_id), current_turn_id

    if ev_type in {"exec_command_begin", "shell_command_begin"}:
        command = payload.get("command") or []
        if isinstance(command, list):
            text = " ".join(str(part) for part in command if str(part).strip())
        else:
            text = _normalize_compact_text(command)
        turn_id = _normalize_compact_text(payload.get("turn_id")) or current_turn_id
        return make_record(kind="tool_call", role="tool", name="shell", text=text, turn_id=turn_id), turn_id

    if ev_type in {"exec_command_end", "shell_command_end"}:
        summary = {
            "stdout": payload.get("stdout"),
            "stderr": payload.get("stderr"),
            "aggregated_output": payload.get("aggregated_output"),
            "formatted_output": payload.get("formatted_output"),
            "exit_code": payload.get("exit_code"),
            "status": payload.get("status"),
        }
        turn_id = _normalize_compact_text(payload.get("turn_id")) or current_turn_id
        return make_record(kind="tool_result", role="tool", name="shell", text=_format_json_value(summary), turn_id=turn_id), turn_id

    if ev_type == "mcp_tool_call_begin":
        invocation = payload.get("invocation") or {}
        tool_name = _normalize_compact_text(invocation.get("tool")) or "mcp"
        args = invocation.get("arguments")
        text = _best_text(_parse_json_text(args))
        if not text:
            text = _normalize_compact_text(args)
        turn_id = _normalize_compact_text(payload.get("turn_id")) or current_turn_id
        return make_record(kind="tool_call", role="tool", name=tool_name, text=text, turn_id=turn_id), turn_id

    if ev_type == "mcp_tool_call_end":
        invocation = payload.get("invocation") or {}
        tool_name = _normalize_compact_text(invocation.get("tool")) or "mcp"
        result = payload.get("result")
        turn_id = _normalize_compact_text(payload.get("turn_id")) or current_turn_id
        return make_record(kind="tool_result", role="tool", name=tool_name, text=_best_text(result), turn_id=turn_id), turn_id

    if ev_type == "warning":
        text = _normalize_compact_text(payload.get("message"))
        if text:
            return make_record(kind="warning", role="system", name=None, text=text, turn_id=current_turn_id), current_turn_id
        return None, current_turn_id

    if ev_type == "error":
        text = _normalize_compact_text(payload.get("message")) or _best_text(payload)
        return make_record(kind="error", role="system", name=None, text=text, turn_id=current_turn_id), current_turn_id

    return None, current_turn_id


def _record_from_rollout_row(
    row: dict[str, Any],
    *,
    source_path: Path,
    line_no: int,
    current_turn_id: str,
) -> tuple[dict[str, Any] | None, str]:
    row_type = str(row.get("type") or "")
    payload = row.get("payload")

    if row_type in {"session_meta", "turn_context"}:
        return None, current_turn_id

    if row_type == "response_item" and isinstance(payload, dict):
        return _response_item_to_record(payload, source_path=source_path, line_no=line_no, current_turn_id=current_turn_id)

    if row_type == "event_msg" and isinstance(payload, dict):
        return _event_msg_to_record(payload, source_path=source_path, line_no=line_no, current_turn_id=current_turn_id)

    if row_type == "token_count":
        return None, current_turn_id

    if payload is None:
        return None, current_turn_id

    text = _best_text(payload)
    if not text:
        return None, current_turn_id
    record = {
        "id": f"{source_path.stem}-{line_no}-context",
        "namespace": source_path.stem,
        "session_id": source_path.stem,
        "thread_id": source_path.stem,
        "turn_id": current_turn_id,
        "kind": "context",
        "role": "system",
        "name": row_type or None,
        "text": text,
        "created_at": _normalize_compact_text(row.get("timestamp")),
        "source": {"kind": row_type or "rollout_row", "path": str(source_path), "line": line_no},
        "payload": payload,
    }
    return record, current_turn_id


def _rollout_rows_to_records(rollout_rows: list[dict[str, Any]], *, source_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    current_turn_id = source_path.stem
    for line_no, row in enumerate(rollout_rows, start=1):
        record, current_turn_id = _record_from_rollout_row(row, source_path=source_path, line_no=line_no, current_turn_id=current_turn_id)
        if record is not None:
            records.append(record)
    return records


def _event_text(record: dict[str, Any]) -> str:
    text = _normalize_compact_text(record.get("text"))
    if text:
        return text
    payload = record.get("payload")
    if payload is None:
        return ""
    if isinstance(payload, (dict, list)):
        return _format_json_value(payload)
    return _normalize_compact_text(payload)


def _record_lines(record: dict[str, Any]) -> list[str]:
    kind = str(record.get("kind") or "")
    role = str(record.get("role") or "")
    name = _normalize_compact_text(record.get("name"))
    text = _event_text(record)
    payload = record.get("payload")

    if name in {"session_meta", "turn_context"}:
        return []
    if kind == "context" and isinstance(payload, dict):
        if any(key in payload for key in ("base_instructions", "developer_instructions", "user_instructions", "system_message")):
            return []

    def payload_lines() -> list[str]:
        if payload is None:
            return []
        preview = _format_json_value(payload) if isinstance(payload, (dict, list)) else _normalize_compact_text(payload)
        if not preview:
            return []
        return ["  payload:", *_indent_lines(preview, "    ")]

    if kind == "user_message":
        return [f"u: {text}"]
    if kind == "assistant_message":
        return [f"a: {text}"]
    if kind == "tool_call":
        headline = f"t: {name or 'tool'}"
        if text:
            first = text.splitlines()[0]
            headline = f"{headline} | {first}"
        return [headline, *payload_lines()]
    if kind == "tool_result":
        headline = f"t-r: {name or 'tool'}"
        if text:
            first = text.splitlines()[0]
            headline = f"{headline} | {first}"
        return [headline, *payload_lines()]
    if kind in {"warning", "error"}:
        label = f"!: {name or kind}"
        lines = [label]
        if text:
            lines.extend(_indent_lines(text))
        if payload is not None:
            lines.extend(payload_lines())
        return lines
    if kind == "context":
        if text:
            return [f"ctx: {name or 'context'}", *_indent_lines(text)]
        return [f"ctx: {name or 'context'}"]
    label = f"ctx: {kind}"
    lines = [label]
    if role and role not in {"system"}:
        lines.append(f"  role: {role}")
    if text:
        lines.extend(_indent_lines(text))
    if payload is not None:
        lines.extend(payload_lines())
    return lines


def _card_body_lines(records: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for record in records:
        record_lines = _record_lines(record)
        if not record_lines:
            continue
        if lines:
            lines.append("")
        lines.extend(record_lines)
    return lines


def _card_turn_id(records: list[dict[str, Any]], fallback: str) -> str:
    for record in records:
        turn_id = _normalize_compact_text(record.get("turn_id"))
        if turn_id:
            return turn_id
    return fallback


def _card_created_at(records: list[dict[str, Any]]) -> str:
    for record in records:
        created_at = _normalize_compact_text(record.get("created_at"))
        if created_at:
            return created_at
    return ""


def _card_summary(records: list[dict[str, Any]]) -> str:
    for record in records:
        if record.get("kind") == "user_message":
            return _normalize_compact_text(record.get("text"))
    for record in records:
        if record.get("kind") == "assistant_message":
            return _normalize_compact_text(record.get("text"))
    return ""


def _group_thread_records(thread_id: str, records: list[dict[str, Any]], thread_order: str) -> list[dict[str, Any]]:
    filtered_records: list[dict[str, Any]] = []
    for record in records:
        if str(record.get("name") or "") in {"session_meta", "turn_context"}:
            continue
        payload = record.get("payload")
        if str(record.get("kind") or "") == "context" and isinstance(payload, dict):
            if any(key in payload for key in ("base_instructions", "developer_instructions", "user_instructions", "system_message")):
                continue
        filtered_records.append(record)

    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    for record in filtered_records:
        if str(record.get("kind")) == "user_message":
            if current:
                groups.append(current)
            current = [record]
        elif current:
            current.append(record)

    if current:
        groups.append(current)

    card_rows: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        turn_id = _card_turn_id(group, f"{thread_id}-turn-{index}")
        body_lines = _card_body_lines(group)
        summary = _card_summary(group)
        created_at = _card_created_at(group)
        card_rows.append(
            {
                "id": f"{thread_id}:{turn_id}:{index}",
                "entry_type": "turn_card",
                "created_at": created_at,
                "title": summary,
                "summary": summary,
                "body": _format_record_body(body_lines),
                "turn_id": turn_id,
                "thread_id": thread_id,
                "thread_order": thread_order,
                "record_count": len(group),
                "card_index": index,
            }
        )
    return card_rows


def _discover_rollout_sources(input_root: Path) -> list[Path]:
    if input_root.is_file():
        return [input_root]
    if not input_root.exists():
        return []
    if input_root.is_dir():
        rollout_files = [path for path in input_root.rglob("rollout-*.jsonl") if path.is_file()]
        if rollout_files:
            return sorted(rollout_files, key=lambda path: str(path))
        return sorted([path for path in input_root.rglob("*.jsonl") if path.is_file()], key=lambda path: str(path))
    return []


def _source_slug(source_path: Path, input_root: Path) -> str:
    try:
        relative = source_path.relative_to(input_root)
    except ValueError:
        relative = source_path
    if str(relative) in {"", "."}:
        return source_path.stem
    parts = list(relative.with_suffix("").parts)
    return "__".join(parts) or source_path.stem


def load_namespace_entries(source_path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    rollout_rows = load_jsonl(source_path)
    if not rollout_rows:
        return entries

    records = _rollout_rows_to_records(rollout_rows, source_path=source_path)
    source_order = datetime.fromtimestamp(source_path.stat().st_mtime).isoformat() if source_path.exists() else source_path.name
    entries.extend(_group_thread_records(source_path.stem, records, source_order))

    entries.sort(
        key=lambda entry: (
            _normalize_compact_text(entry.get("thread_order")),
            _normalize_compact_text(entry.get("thread_id")),
            int(entry.get("card_index") or 0),
        )
    )
    return entries


def build_card_layout(entry: dict[str, Any], col_width: int, cfg: LayoutConfig, fonts: dict[str, ImageFont.FreeTypeFont]) -> CardLayout:
    wrap_chars = max(cfg.min_width_chars, int(col_width / cfg.width_chars_scale))
    id_lines = wrap_text(entry["id"], wrap_chars)
    title_lines = wrap_text(entry.get("title") or "", wrap_chars) if cfg.show_title and entry.get("title") else []
    body_lines = wrap_text(entry.get("body") or "", wrap_chars)

    meta_h = line_height(fonts["meta"])
    body_h = line_height(fonts["body"])
    height = cfg.card_pad * 2 + len(id_lines) * meta_h + len(title_lines) * body_h + len(body_lines) * body_h
    if title_lines or body_lines:
        height += 2
    return CardLayout(
        entry_id=entry["id"],
        entry_type=entry.get("entry_type") or "",
        created_at=entry.get("created_at") or "",
        segment_index=1,
        segment_total=1,
        segment_start=0,
        segment_end=len(body_lines),
        id_lines=id_lines,
        title_lines=title_lines,
        body_lines=body_lines,
        height=height,
    )


def split_card_layout(entry: dict[str, Any], col_width: int, cfg: LayoutConfig, fonts: dict[str, ImageFont.FreeTypeFont]) -> list[CardLayout]:
    base_layout = build_card_layout(entry, col_width, cfg, fonts)
    meta_h = line_height(fonts["meta"])
    body_h = line_height(fonts["body"])
    column_height = max_card_height(cfg)

    fixed_height = cfg.card_pad * 2 + len(base_layout.id_lines) * meta_h + len(base_layout.title_lines) * body_h
    if base_layout.body_lines:
        fixed_height += 2

    if fixed_height > column_height:
        raise ValueError(
            f"Entry {entry['id']} does not fit in an empty frame even before body splitting with the current layout"
        )

    if not base_layout.body_lines:
        return [base_layout]

    max_body_lines = (column_height - fixed_height) // body_h
    if max_body_lines >= len(base_layout.body_lines):
        return [base_layout]

    max_body_lines = (column_height - fixed_height - meta_h - 2) // body_h
    if max_body_lines < 1:
        raise ValueError(
            f"Entry {entry['id']} does not fit in an empty frame even after continuation splitting with the current layout"
        )

    segments: list[CardLayout] = []
    total_segments = (len(base_layout.body_lines) + max_body_lines - 1) // max_body_lines
    for segment_index in range(total_segments):
        start = segment_index * max_body_lines
        end = min(len(base_layout.body_lines), start + max_body_lines)
        chunk = base_layout.body_lines[start:end]
        height = fixed_height + len(chunk) * body_h + meta_h + 2
        segments.append(
            CardLayout(
                entry_id=base_layout.entry_id,
                entry_type=base_layout.entry_type,
                created_at=base_layout.created_at,
                segment_index=segment_index + 1,
                segment_total=total_segments,
                segment_start=start,
                segment_end=end,
                id_lines=base_layout.id_lines,
                title_lines=base_layout.title_lines,
                body_lines=chunk,
                height=height,
            )
        )
    return segments


def pack_frame(cards: list[CardLayout], start_index: int, cfg: LayoutConfig) -> tuple[list[PlacedCard], int]:
    usable_w = cfg.width - 2 * cfg.margin - (cfg.cols - 1) * cfg.col_gap
    col_width = usable_w // cfg.cols
    top_y = cfg.header_h + 10
    max_y = cfg.height - cfg.footer_h - 6

    placed: list[PlacedCard] = []
    idx = start_index
    col = 0
    y = top_y

    while idx < len(cards):
        layout = cards[idx]
        if y + layout.height > max_y:
            col += 1
            if col >= cfg.cols:
                break
            y = top_y
            continue

        x = cfg.margin + col * (col_width + cfg.col_gap)
        placed.append(
            PlacedCard(
                x=x,
                y=y,
                width=col_width,
                layout=layout,
                entry_type=layout.entry_type,
                created_at=layout.created_at,
            )
        )
        y += layout.height + cfg.card_gap
        idx += 1

    if not placed:
        raise ValueError(f"Entry {cards[start_index].entry_id} does not fit in an empty frame with the current layout")

    return placed, idx


def render_frame(
    placed: list[PlacedCard],
    namespace: str,
    frame_index: int,
    total_frames: int,
    output_path: Path,
    cfg: LayoutConfig,
    fonts: dict[str, ImageFont.FreeTypeFont],
) -> None:
    bg = "#f7f5ef"
    accent = "#214a7a"
    muted = "#5a5a5a"
    line_color = "#d8d2c8"
    card_fill = "#ffffff"
    fg = "#111111"
    stripe_trace = "#4e6a8e"
    stripe_user = "#8e4e4e"

    image = Image.new("RGB", (cfg.width, cfg.height), bg)
    draw = ImageDraw.Draw(image)

    draw.text((cfg.margin, 12), f"LEDGER FRAMES | {namespace}", font=fonts["header"], fill=accent)
    draw.text(
        (cfg.margin, 33),
        f"frame {frame_index:04d} of {total_frames:04d} | {len(placed)} entries | {cfg.width}x{cfg.height}",
        font=fonts["subheader"],
        fill=muted,
    )
    draw.line((cfg.margin, cfg.header_h - 10, cfg.width - cfg.margin, cfg.header_h - 10), fill=line_color, width=1)

    id_h = line_height(fonts["meta"])
    body_h = line_height(fonts["body"])

    for card in placed:
        x0 = card.x
        y0 = card.y
        x1 = x0 + card.width
        y1 = y0 + card.layout.height
        draw.rounded_rectangle((x0, y0, x1, y1), radius=6, fill=card_fill, outline=line_color, width=1)
        if cfg.show_stripe:
            stripe = stripe_trace if card.entry_type == "context" else stripe_user
            draw.rectangle((x0 + 1, y0 + 1, x0 + 6, y1 - 1), fill=stripe)

        tx = x0 + cfg.card_pad + 2
        ty = y0 + cfg.card_pad - 1
        for line in card.layout.id_lines:
            draw.text((tx, ty), line, font=fonts["meta"], fill=muted)
            ty += id_h
        if card.layout.segment_total > 1:
            draw.text(
                (tx, ty),
                f"part {card.layout.segment_index}/{card.layout.segment_total}",
                font=fonts["meta"],
                fill=muted,
            )
            ty += id_h
        if card.layout.title_lines:
            ty += 1
            for line in card.layout.title_lines:
                draw.text((tx, ty), line, font=fonts["body"], fill=fg)
                ty += body_h
        if card.layout.body_lines:
            if card.layout.title_lines:
                ty += 1
            for line in card.layout.body_lines:
                draw.text((tx, ty), line, font=fonts["body"], fill=fg)
                ty += body_h

    draw.line((cfg.margin, cfg.height - cfg.footer_h, cfg.width - cfg.margin, cfg.height - cfg.footer_h), fill=line_color, width=1)
    draw.text(
        (cfg.margin, cfg.height - cfg.footer_h + 5),
        "Source order preserved | overflow continues on the next frame",
        font=fonts["footer"],
        fill=muted,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def compile_namespace(source_path: Path, output_root: Path, cfg: LayoutConfig, font_path: Path, namespace: str | None = None) -> dict[str, Any]:
    source_path = source_path.expanduser().resolve()
    namespace = namespace or source_path.stem
    namespace_root = output_root / "v1" / "namespaces" / namespace
    frames_dir = namespace_root / "frames"
    manifest_path = namespace_root / "manifest.jsonl"
    summary_path = namespace_root / "summary.json"

    entries = load_namespace_entries(source_path)
    if not entries:
        return {
            "namespace": namespace,
            "input_source_path": str(source_path),
            "output_namespace_dir": str(namespace_root),
            "frames_dir": str(frames_dir),
            "manifest_path": str(manifest_path),
            "summary_path": str(summary_path),
            "frames_written": 0,
            "cards_written": 0,
            "threads_compiled": 0,
            "skipped": True,
        }

    if namespace_root.exists():
        shutil.rmtree(namespace_root)

    fonts = load_fonts(font_path, cfg)
    usable_w = cfg.width - 2 * cfg.margin - (cfg.cols - 1) * cfg.col_gap
    col_width = usable_w // cfg.cols
    cards: list[CardLayout] = []
    for entry in entries:
        cards.extend(split_card_layout(entry, col_width, cfg, fonts))

    frame_rows: list[dict[str, Any]] = []
    start_index = 0
    frame_index = 1
    while start_index < len(cards):
        placed, next_index = pack_frame(cards, start_index, cfg)
        output_path = frames_dir / f"frame_{frame_index:04d}.png"
        render_frame(placed, namespace, frame_index, 0, output_path, cfg, fonts)
        frame_rows.append(
            {
                "namespace": namespace,
                "frame_index": frame_index,
                "image_path": str(output_path),
                "entry_ids": [card.layout.entry_id for card in placed],
                "cards": [
                    {
                        "entry_id": card.layout.entry_id,
                        "entry_type": card.layout.entry_type,
                        "segment_index": card.layout.segment_index,
                        "segment_total": card.layout.segment_total,
                        "segment_start": card.layout.segment_start,
                        "segment_end": card.layout.segment_end,
                        "thread_id": card.layout.entry_id.split(":", 1)[0],
                    }
                    for card in placed
                ],
                "entry_count": len(placed),
                "start_index": start_index,
                "end_index": next_index,
            }
        )
        start_index = next_index
        frame_index += 1

    total_frames = len(frame_rows)
    for row in frame_rows:
        row["total_frames"] = total_frames

    frames_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("\n".join(json.dumps(row, ensure_ascii=True) for row in frame_rows) + "\n", encoding="utf-8")
    summary = {
        "namespace": namespace,
        "input_source_path": str(source_path),
        "output_namespace_dir": str(namespace_root),
        "frames_dir": str(frames_dir),
        "manifest_path": str(manifest_path),
        "summary_path": str(summary_path),
        "frames_written": total_frames,
        "cards_written": len(cards),
        "threads_compiled": len({entry.get("thread_id") for entry in entries}),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def compile_all_namespaces(
    input_root: Path,
    output_root: Path,
    cfg: LayoutConfig,
    font_path: Path,
    namespaces: list[str] | None = None,
) -> dict[str, Any]:
    input_root = input_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    if namespaces is None:
        source_paths = _discover_rollout_sources(input_root)
    elif input_root.is_file():
        source_paths = [input_root]
    else:
        source_paths = [input_root / namespace for namespace in namespaces]

    compiled: list[dict[str, Any]] = []
    for source_path in sorted(source_paths, key=lambda path: str(path)):
        if not source_path.exists():
            continue
        compiled.append(
            compile_namespace(
                source_path,
                output_root,
                cfg,
                font_path,
                namespace=_source_slug(source_path, input_root),
            )
        )

    return {
        "input_root": str(input_root),
        "output_root": str(output_root),
        "namespaces_compiled": len(compiled),
        "frames_written": sum(int(item.get("frames_written") or 0) for item in compiled),
        "cards_written": sum(int(item.get("cards_written") or 0) for item in compiled),
        "compiled": compiled,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile Codex session frames.")
    parser.add_argument(
        "--input-root",
        type=Path,
        default=DEFAULT_INPUT_ROOT,
        help="Codex session root containing rollout-*.jsonl files",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Output directory for rendered frame images",
    )
    parser.add_argument(
        "--font-path",
        type=Path,
        default=DEFAULT_FONT,
        help="Mono font used for the frame renderer",
    )
    parser.add_argument(
        "--namespace",
        action="append",
        dest="namespaces",
        help="Session namespace to compile (repeatable). Defaults to all discovered rollout files.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    cfg = LayoutConfig()
    summary = compile_all_namespaces(
        input_root=args.input_root,
        output_root=args.output_root,
        cfg=cfg,
        font_path=args.font_path,
        namespaces=args.namespaces,
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
