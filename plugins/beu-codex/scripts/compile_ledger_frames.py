#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import io
import json
import shutil
import textwrap
from dataclasses import dataclass, field
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
    compact_tool_details: bool = True


@dataclass(frozen=True)
class BodyBlock:
    kind: str
    text_lines: list[str] = field(default_factory=list)
    image_data: bytes | None = None
    image_width: int = 0
    image_height: int = 0
    height: int = 0


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
    body_blocks: list[BodyBlock]
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


def _first_nonempty_line(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line:
            return line
    return ""


def _last_nonempty_line(text: str) -> str:
    for raw_line in reversed(text.splitlines()):
        line = raw_line.strip()
        if line:
            return line
    return ""


def _truncate_preview(text: str, limit: int = 48) -> str:
    compact = _normalize_compact_text(text)
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


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
        image_count = 0
        for item in content:
            if isinstance(item, dict):
                text = _normalize_compact_text(item.get("text"))
                if text:
                    pieces.append(text)
                    continue
                if _normalize_compact_text(item.get("image_url")) or str(item.get("type") or "") in {
                    "input_image",
                    "output_image",
                    "image",
                }:
                    image_count += 1
            else:
                text = _normalize_compact_text(item)
                if text:
                    pieces.append(text)
        if pieces:
            return "\n".join(pieces).strip()
        if image_count:
            return f"[{image_count} image{'s' if image_count != 1 else ''}]"
    return _best_text(content)


def _make_text_block(text: str, body_h: int, wrap_chars: int) -> BodyBlock | None:
    text = _normalize_compact_text(text)
    if not text:
        return None
    lines = wrap_text(text, wrap_chars)
    return BodyBlock(kind="text", text_lines=lines, height=max(1, len(lines)) * body_h)


def _decode_data_uri_image(image_url: Any) -> tuple[bytes, int, int] | None:
    text = _normalize_compact_text(image_url)
    if not text.startswith("data:image/") or "," not in text:
        return None
    try:
        _, encoded = text.split(",", 1)
        data = base64.b64decode(encoded, validate=False)
    except Exception:  # noqa: BLE001
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
    except Exception:  # noqa: BLE001
        return None
    return data, width, height


def _make_image_block(image_url: Any, col_width: int, cfg: LayoutConfig, body_h: int) -> BodyBlock | None:
    decoded = _decode_data_uri_image(image_url)
    if decoded is None:
        return None
    data, src_width, src_height = decoded
    max_width = max(1, col_width - cfg.card_pad * 2 - 6)
    max_height = max(1, max_card_height(cfg) // 2)
    scale = min(max_width / max(1, src_width), max_height / max(1, src_height), 1.0)
    render_width = max(1, int(src_width * scale))
    render_height = max(1, int(src_height * scale))
    return BodyBlock(
        kind="image",
        image_data=data,
        image_width=render_width,
        image_height=render_height,
        height=render_height + max(4, body_h // 2),
    )


def _split_text_block(block: BodyBlock, max_lines: int, body_h: int) -> list[BodyBlock]:
    if block.kind != "text" or max_lines < 1 or len(block.text_lines) <= max_lines:
        return [block]
    chunks: list[BodyBlock] = []
    for start in range(0, len(block.text_lines), max_lines):
        lines = block.text_lines[start : start + max_lines]
        chunks.append(BodyBlock(kind="text", text_lines=lines, height=max(1, len(lines)) * body_h))
    return chunks


def _fit_image_block(block: BodyBlock, max_body_height: int, body_h: int) -> BodyBlock:
    if block.kind != "image" or block.image_data is None or block.height <= max_body_height:
        return block
    max_render_height = max(1, max_body_height - max(4, body_h // 2))
    if block.image_height <= max_render_height:
        return BodyBlock(
            kind="image",
            image_data=block.image_data,
            image_width=block.image_width,
            image_height=block.image_height,
            height=max_render_height + max(4, body_h // 2),
        )
    scale = max_render_height / max(1, block.image_height)
    render_width = max(1, int(block.image_width * scale))
    render_height = max(1, int(block.image_height * scale))
    return BodyBlock(
        kind="image",
        image_data=block.image_data,
        image_width=render_width,
        image_height=render_height,
        height=render_height + max(4, body_h // 2),
    )


def _content_blocks(content: Any, body_h: int, wrap_chars: int, col_width: int, cfg: LayoutConfig) -> list[BodyBlock]:
    blocks: list[BodyBlock] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                item_type = str(item.get("type") or "")
                text = _normalize_compact_text(item.get("text") or item.get("content") or item.get("value"))
                if item_type in {"input_image", "output_image", "image"} or _normalize_compact_text(item.get("image_url")):
                    image_block = _make_image_block(item.get("image_url"), col_width, cfg, body_h)
                    if image_block is not None:
                        blocks.append(image_block)
                        continue
                if text:
                    text_block = _make_text_block(text, body_h, wrap_chars)
                    if text_block is not None:
                        blocks.append(text_block)
                        continue
            else:
                text_block = _make_text_block(str(item), body_h, wrap_chars)
                if text_block is not None:
                    blocks.append(text_block)
    elif content is not None:
        text_block = _make_text_block(_best_text(content), body_h, wrap_chars)
        if text_block is not None:
            blocks.append(text_block)
    return blocks


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
        return None, current_turn_id

    if ev_type == "error":
        return None, current_turn_id

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
    return None, current_turn_id


def _rollout_rows_to_records(rollout_rows: list[dict[str, Any]], *, source_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    current_turn_id = source_path.stem
    for line_no, row in enumerate(rollout_rows, start=1):
        record, current_turn_id = _record_from_rollout_row(row, source_path=source_path, line_no=line_no, current_turn_id=current_turn_id)
        if record is not None:
            records.append(record)

    deduped: list[dict[str, Any]] = []
    for record in records:
        if deduped:
            prev = deduped[-1]
            same_kind = str(prev.get("kind")) == str(record.get("kind"))
            same_text = _normalize_compact_text(prev.get("text")) == _normalize_compact_text(record.get("text"))
            same_turn = _normalize_compact_text(prev.get("turn_id")) == _normalize_compact_text(record.get("turn_id"))
            same_name = _normalize_compact_text(prev.get("name")) == _normalize_compact_text(record.get("name"))
            if same_kind and same_text and same_turn and same_name:
                continue
        deduped.append(record)
    return deduped


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


def _record_lines(record: dict[str, Any], compact_tool_details: bool = True) -> list[str]:
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
    if kind == "tool_call" and not compact_tool_details:
        headline = f"t: {name or 'tool'}"
        if text:
            first = text.splitlines()[0]
            headline = f"{headline} | {first}"
        return [headline, *payload_lines()]
    if kind == "tool_result" and not compact_tool_details:
        headline = f"t-r: {name or 'tool'}"
        if text:
            first = text.splitlines()[0]
            headline = f"{headline} | {first}"
        return [headline, *payload_lines()]
    if kind in {"warning", "error", "context", "tool_call", "tool_result"}:
        return []


def _record_body_blocks(
    record: dict[str, Any],
    *,
    compact_tool_details: bool,
    body_h: int,
    wrap_chars: int,
    col_width: int,
    cfg: LayoutConfig,
) -> list[BodyBlock]:
    kind = str(record.get("kind") or "")
    payload = record.get("payload")

    if kind in {"user_message", "assistant_message"}:
        content = payload.get("content") if isinstance(payload, dict) else None
        blocks = _content_blocks(content, body_h, wrap_chars, col_width, cfg)
        if blocks:
            return blocks
        text = _event_text(record)
        block = _make_text_block(text, body_h, wrap_chars)
        return [block] if block is not None else []

    if kind == "tool_call" and compact_tool_details:
        text = _event_text(record)
        block = _make_text_block(text, body_h, wrap_chars)
        return [block] if block is not None else []

    if kind == "tool_result" and compact_tool_details:
        text = _event_text(record)
        block = _make_text_block(text, body_h, wrap_chars)
        return [block] if block is not None else []

    lines = _record_lines(record, compact_tool_details=compact_tool_details)
    if not lines:
        return []
    return [BodyBlock(kind="text", text_lines=lines, height=max(1, len(lines)) * body_h)]


def _summarize_tool_activity(tool_calls: int, tool_results: int) -> list[str]:
    if tool_calls == 0 and tool_results == 0:
        return []
    parts: list[str] = []
    if tool_calls:
        parts.append(f"{tool_calls} call{'s' if tool_calls != 1 else ''}")
    if tool_results:
        parts.append(f"{tool_results} result{'s' if tool_results != 1 else ''}")
    return [f"tools: {', '.join(parts)}"]


def _card_body_blocks(
    records: list[dict[str, Any]],
    *,
    compact_tool_details: bool,
    body_h: int,
    wrap_chars: int,
    col_width: int,
    cfg: LayoutConfig,
) -> list[BodyBlock]:
    blocks: list[BodyBlock] = []
    pending_calls = 0
    pending_results = 0

    def flush_tools() -> None:
        nonlocal pending_calls, pending_results
        tool_lines = _summarize_tool_activity(pending_calls, pending_results) if compact_tool_details else []
        if tool_lines:
            block = _make_text_block(_format_record_body(tool_lines), body_h, wrap_chars)
            if block is not None:
                blocks.append(block)
        pending_calls = 0
        pending_results = 0

    for record in records:
        kind = str(record.get("kind") or "")
        if kind in {"tool_call", "tool_result"} and compact_tool_details:
            if kind == "tool_call":
                pending_calls += 1
            else:
                pending_results += 1
            continue

        flush_tools()
        record_blocks = _record_body_blocks(
            record,
            compact_tool_details=compact_tool_details,
            body_h=body_h,
            wrap_chars=wrap_chars,
            col_width=col_width,
            cfg=cfg,
        )
        if record_blocks:
            blocks.extend(record_blocks)
    flush_tools()
    return blocks


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


def _group_thread_records(
    thread_id: str,
    records: list[dict[str, Any]],
    thread_order: str,
    *,
    compact_tool_details: bool,
) -> list[dict[str, Any]]:
    filtered_records: list[dict[str, Any]] = []
    for record in records:
        if str(record.get("name") or "") in {"session_meta", "turn_context"}:
            continue
        payload = record.get("payload")
        if str(record.get("kind") or "") in {"context", "warning", "error"}:
            continue
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
        summary = _card_summary(group)
        created_at = _card_created_at(group)
        card_rows.append(
            {
                "id": f"{thread_id}:{turn_id}:{index}",
                "entry_type": "turn_card",
                "created_at": created_at,
                "title": summary,
                "summary": summary,
                "records": group,
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
            return sorted(
                rollout_files,
                key=lambda path: (
                    path.stat().st_mtime if path.exists() else 0.0,
                    str(path),
                ),
            )
        return sorted(
            [path for path in input_root.rglob("*.jsonl") if path.is_file()],
            key=lambda path: (
                path.stat().st_mtime if path.exists() else 0.0,
                str(path),
            ),
        )
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


def _thread_separator_entry(thread_id: str, thread_order: str, source_path: Path) -> dict[str, Any]:
    return {
        "id": f"{thread_id}:thread-separator",
        "entry_type": "thread_separator",
        "created_at": thread_order,
        "title": "",
        "summary": "",
        "body": "\n".join(
            [
                "────────────────────────",
                f"new thread: {thread_id}",
                f"source: {source_path.name}",
            ]
        ),
        "turn_id": f"{thread_id}:thread-separator",
        "thread_id": thread_id,
        "thread_order": thread_order,
        "record_count": 0,
        "card_index": -1,
    }


def load_namespace_entries(source_path: Path, *, compact_tool_details: bool = True) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    rollout_rows = load_jsonl(source_path)
    if not rollout_rows:
        return entries

    records = _rollout_rows_to_records(rollout_rows, source_path=source_path)
    source_order = datetime.fromtimestamp(source_path.stat().st_mtime).isoformat() if source_path.exists() else source_path.name
    entries.extend(
        _group_thread_records(
            source_path.stem,
            records,
            source_order,
            compact_tool_details=compact_tool_details,
        )
    )

    entries.sort(
        key=lambda entry: (
            _normalize_compact_text(entry.get("thread_order")),
            _normalize_compact_text(entry.get("thread_id")),
            int(entry.get("card_index") or 0),
        )
    )
    return entries


def _combine_thread_entries(source_paths: list[Path], *, compact_tool_details: bool) -> tuple[list[dict[str, Any]], int]:
    combined: list[dict[str, Any]] = []
    threads_compiled = 0

    for source_path in source_paths:
        entries = load_namespace_entries(source_path, compact_tool_details=compact_tool_details)
        if not entries:
            continue
        thread_id = _normalize_compact_text(entries[0].get("thread_id")) or source_path.stem
        thread_order = _normalize_compact_text(entries[0].get("thread_order")) or source_path.name
        if combined:
            combined.append(_thread_separator_entry(thread_id, thread_order, source_path))
        combined.extend(entries)
        threads_compiled += 1

    return combined, threads_compiled


def build_card_layout(entry: dict[str, Any], col_width: int, cfg: LayoutConfig, fonts: dict[str, ImageFont.FreeTypeFont]) -> CardLayout:
    wrap_chars = max(cfg.min_width_chars, int(col_width / cfg.width_chars_scale))
    id_lines = wrap_text(entry["id"], wrap_chars)
    title_lines = wrap_text(entry.get("title") or "", wrap_chars) if cfg.show_title and entry.get("title") else []
    meta_h = line_height(fonts["meta"])
    body_h = line_height(fonts["body"])
    body_blocks = _card_body_blocks(
        entry.get("records") or [],
        compact_tool_details=cfg.compact_tool_details,
        body_h=body_h,
        wrap_chars=wrap_chars,
        col_width=col_width,
        cfg=cfg,
    )
    body_gap = max(3, body_h // 2)
    height = cfg.card_pad * 2 + len(id_lines) * meta_h + len(title_lines) * body_h
    if body_blocks:
        height += 2
        height += sum(block.height for block in body_blocks)
        height += body_gap * (len(body_blocks) - 1)
    return CardLayout(
        entry_id=entry["id"],
        entry_type=entry.get("entry_type") or "",
        created_at=entry.get("created_at") or "",
        segment_index=1,
        segment_total=1,
        segment_start=0,
        segment_end=len(body_blocks),
        id_lines=id_lines,
        title_lines=title_lines,
        body_blocks=body_blocks,
        height=height,
    )


def split_card_layout(entry: dict[str, Any], col_width: int, cfg: LayoutConfig, fonts: dict[str, ImageFont.FreeTypeFont]) -> list[CardLayout]:
    base_layout = build_card_layout(entry, col_width, cfg, fonts)
    meta_h = line_height(fonts["meta"])
    body_h = line_height(fonts["body"])
    column_height = max_card_height(cfg)
    body_gap = max(3, body_h // 2)

    fixed_height = cfg.card_pad * 2 + len(base_layout.id_lines) * meta_h + len(base_layout.title_lines) * body_h
    if base_layout.body_blocks:
        fixed_height += 2

    if fixed_height > column_height:
        raise ValueError(
            f"Entry {entry['id']} does not fit in an empty frame even before body splitting with the current layout"
        )

    if not base_layout.body_blocks:
        return [base_layout]

    max_single_body_height = max(1, column_height - fixed_height - (meta_h + 2))
    normalized_blocks: list[BodyBlock] = []
    for block in base_layout.body_blocks:
        if block.kind == "text":
            normalized_blocks.extend(_split_text_block(block, max(1, max_single_body_height // body_h), body_h))
        elif block.kind == "image":
            normalized_blocks.append(_fit_image_block(block, max_single_body_height, body_h))
        else:
            normalized_blocks.append(block)

    total_body_height = sum(block.height for block in normalized_blocks)
    total_body_height += body_gap * (len(normalized_blocks) - 1)
    if fixed_height + total_body_height <= column_height:
        return [
            CardLayout(
                entry_id=base_layout.entry_id,
                entry_type=base_layout.entry_type,
                created_at=base_layout.created_at,
                segment_index=1,
                segment_total=1,
                segment_start=0,
                segment_end=len(normalized_blocks),
                id_lines=base_layout.id_lines,
                title_lines=base_layout.title_lines,
                body_blocks=normalized_blocks,
                height=cfg.card_pad * 2 + len(base_layout.id_lines) * meta_h + len(base_layout.title_lines) * body_h + 2 + total_body_height,
            )
        ]

    segment_header = meta_h + 2
    segments_data: list[tuple[int, int, int, list[BodyBlock], int]] = []
    start = 0
    blocks = normalized_blocks
    while start < len(blocks):
        current_height = fixed_height + segment_header
        end = start
        while end < len(blocks):
            add_height = blocks[end].height
            if end > start:
                add_height += body_gap
            if current_height + add_height > column_height:
                break
            current_height += add_height
            end += 1
        if end == start:
            raise ValueError(
                f"Entry {entry['id']} does not fit in an empty frame even after continuation splitting with the current layout"
            )
        segments_data.append((start, end, current_height, blocks[start:end], len(blocks)))
        start = end

    total_segments = len(segments_data)
    segments: list[CardLayout] = []
    for segment_index, (start, end, height, chunk, _) in enumerate(segments_data, start=1):
        segments.append(
            CardLayout(
                entry_id=base_layout.entry_id,
                entry_type=base_layout.entry_type,
                created_at=base_layout.created_at,
                segment_index=segment_index,
                segment_total=total_segments,
                segment_start=start,
                segment_end=end,
                id_lines=base_layout.id_lines,
                title_lines=base_layout.title_lines,
                body_blocks=chunk,
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
    separator_fill = "#f0ebe0"
    fg = "#111111"
    stripe_trace = "#4e6a8e"
    stripe_user = "#8e4e4e"
    stripe_separator = "#b8843d"
    body_gap = max(3, line_height(fonts["body"]) // 2)

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
        is_separator = card.entry_type == "thread_separator"
        fill = separator_fill if is_separator else card_fill
        outline = stripe_separator if is_separator else line_color
        draw.rounded_rectangle((x0, y0, x1, y1), radius=6, fill=fill, outline=outline, width=2 if is_separator else 1)
        if cfg.show_stripe or is_separator:
            stripe = stripe_separator if is_separator else (stripe_trace if card.entry_type == "context" else stripe_user)
            draw.rectangle((x0 + 1, y0 + 1, x0 + 8, y1 - 1), fill=stripe)

        tx = x0 + cfg.card_pad + 2
        ty = y0 + cfg.card_pad - 1
        for line in card.layout.id_lines:
            draw.text((tx, ty), line, font=fonts["meta"], fill=muted)
            ty += id_h
        if is_separator:
            ty += 2
            sep_text = "NEW THREAD"
            sep_w = draw.textlength(sep_text, font=fonts["body"])
            draw.text((x0 + (card.width - sep_w) / 2, ty), sep_text, font=fonts["body"], fill=accent)
            ty += body_h + 2
            draw.line((tx, ty, x1 - cfg.card_pad, ty), fill=outline, width=1)
            ty += 4
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
        if card.layout.body_blocks:
            if card.layout.title_lines:
                ty += 1
            for block_index, block in enumerate(card.layout.body_blocks):
                if block_index:
                    ty += body_gap
                if block.kind == "image" and block.image_data:
                    box = (tx, ty, tx + block.image_width + 2, ty + block.image_height + 2)
                    draw.rounded_rectangle(box, radius=4, fill=card_fill, outline=line_color, width=1)
                    try:
                        resample_filter = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)
                        with Image.open(io.BytesIO(block.image_data)) as src_image:
                            rendered = src_image.convert("RGBA").resize(
                                (block.image_width, block.image_height),
                                resample_filter,
                            )
                        image.paste(rendered, (tx + 1, ty + 1), rendered)
                    except Exception:  # noqa: BLE001
                        placeholder = "[image]"
                        draw.text((tx + 3, ty + 2), placeholder, font=fonts["body"], fill=muted)
                    ty += block.height
                    continue
                for line in block.text_lines:
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


def compile_entries(
    entries: list[dict[str, Any]],
    output_root: Path,
    cfg: LayoutConfig,
    font_path: Path,
    *,
    namespace: str,
    input_source_path: str,
    threads_compiled: int,
) -> dict[str, Any]:
    namespace_root = output_root / "v1" / "namespaces" / namespace
    frames_dir = namespace_root / "frames"
    manifest_path = namespace_root / "manifest.jsonl"
    summary_path = namespace_root / "summary.json"

    if not entries:
        return {
            "namespace": namespace,
            "input_source_path": input_source_path,
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

    frame_groups: list[tuple[int, int, list[PlacedCard]]] = []
    start_index = 0
    while start_index < len(cards):
        placed, next_index = pack_frame(cards, start_index, cfg)
        frame_groups.append((start_index, next_index, placed))
        start_index = next_index

    total_frames = len(frame_groups)
    frame_rows: list[dict[str, Any]] = []
    for frame_index, (start_index, next_index, placed) in enumerate(frame_groups, start=1):
        output_path = frames_dir / f"frame_{frame_index:04d}.png"
        render_frame(placed, namespace, frame_index, total_frames, output_path, cfg, fonts)
        frame_rows.append(
            {
                "namespace": namespace,
                "frame_index": frame_index,
                "total_frames": total_frames,
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

    frames_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("\n".join(json.dumps(row, ensure_ascii=True) for row in frame_rows) + "\n", encoding="utf-8")
    summary = {
        "namespace": namespace,
        "input_source_path": input_source_path,
        "output_namespace_dir": str(namespace_root),
        "frames_dir": str(frames_dir),
        "manifest_path": str(manifest_path),
        "summary_path": str(summary_path),
        "frames_written": total_frames,
        "cards_written": len(cards),
        "threads_compiled": threads_compiled,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def compile_namespace(source_path: Path, output_root: Path, cfg: LayoutConfig, font_path: Path, namespace: str | None = None) -> dict[str, Any]:
    source_path = source_path.expanduser().resolve()
    namespace = namespace or source_path.stem
    entries = load_namespace_entries(source_path, compact_tool_details=cfg.compact_tool_details)
    return compile_entries(
        entries,
        output_root,
        cfg,
        font_path,
        namespace=namespace,
        input_source_path=str(source_path),
        threads_compiled=len({entry.get("thread_id") for entry in entries}),
    )


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

    source_paths = [path for path in source_paths if path.exists()]
    source_paths = sorted(
        source_paths,
        key=lambda path: (
            path.stat().st_mtime if path.exists() else 0.0,
            str(path),
        ),
    )

    combined_entries, threads_compiled = _combine_thread_entries(
        source_paths,
        compact_tool_details=cfg.compact_tool_details,
    )
    compiled: list[dict[str, Any]] = []
    if combined_entries:
        compiled.append(
            compile_entries(
                combined_entries,
                output_root,
                cfg,
                font_path,
                namespace="all_threads",
                input_source_path=str(input_root),
                threads_compiled=threads_compiled,
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
    compact_group = parser.add_mutually_exclusive_group()
    compact_group.add_argument(
        "--compact-tool-details",
        dest="compact_tool_details",
        action="store_true",
        help="Render tool calls and tool results as compact one-line previews.",
    )
    compact_group.add_argument(
        "--no-compact-tool-details",
        dest="compact_tool_details",
        action="store_false",
        help="Render full tool call and result payloads.",
    )
    parser.set_defaults(compact_tool_details=LayoutConfig.compact_tool_details)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    cfg = LayoutConfig(compact_tool_details=args.compact_tool_details)
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
