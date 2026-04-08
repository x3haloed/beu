#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from compile_ledger_frames import (
    DEFAULT_FONT,
    LayoutConfig,
    _best_text,
    _event_msg_to_record,
    _message_text,
    _normalize_compact_text,
    _parse_json_text,
    _response_item_to_record,
    compile_entries,
)

DEFAULT_INPUT_DB = Path("/Users/chad/Downloads/betterclaw.db")
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "output" / "turn_event_frames"

EVENT_TABLE_HINTS = ("turn", "event", "message", "conversation", "thread")
TEXT_COLUMNS = ("text", "message", "content", "body", "output", "result", "summary")
JSON_COLUMNS = ("payload", "data", "event", "message", "request", "response", "metadata", "json")
TYPE_COLUMNS = ("type", "kind", "event_type", "event_name", "name")
THREAD_COLUMNS = ("thread_id", "conversation_id", "session_id", "chat_id")
TURN_COLUMNS = ("turn_id", "run_id", "step_id", "request_id", "parent_id")
CREATED_COLUMNS = ("created_at", "timestamp", "time", "datetime", "updated_at")
IMAGE_KEYS = ("image", "image_url", "screenshot", "screenshot_url", "snapshot", "thumbnail")


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _table_names(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_schema
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({_quote_ident(table)})").fetchall()
    return [str(row["name"]) for row in rows]


def _first_column(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    by_lower = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate in by_lower:
            return by_lower[candidate]
    return None


def _parse_jsonish(value: Any) -> Any:
    parsed = _parse_json_text(value)
    return parsed


def _jsonish_columns(row: dict[str, Any]) -> list[str]:
    columns: list[str] = []
    for column, value in row.items():
        if value is None:
            continue
        lower = column.lower()
        text = str(value).lstrip()
        if lower in JSON_COLUMNS or lower.endswith("_json") or text.startswith(("{", "[")):
            columns.append(column)
    return columns


def _build_payload(row: dict[str, Any], type_col: str | None, text_col: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}

    for column in _jsonish_columns(row):
        parsed = _parse_jsonish(row.get(column))
        if isinstance(parsed, dict):
            payload.update(parsed)
        elif parsed is not None and column not in payload:
            payload[column] = parsed

    for column, value in row.items():
        if value is None or column in payload:
            continue
        payload[column] = value

    if type_col and row.get(type_col) is not None and not _normalize_compact_text(payload.get("type")):
        payload["type"] = row[type_col]

    if text_col and row.get(text_col) is not None:
        payload.setdefault("message", row[text_col])
        payload.setdefault("text", row[text_col])

    return payload


def _is_data_image(value: Any) -> bool:
    return isinstance(value, str) and value.lstrip().startswith("data:image/") and "," in value


def _extract_image_urls(value: Any) -> list[str]:
    images: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_lower = str(key).lower()
            if any(image_key in key_lower for image_key in IMAGE_KEYS) and _is_data_image(item):
                images.append(str(item).strip())
                continue
            if isinstance(item, (dict, list)):
                images.extend(_extract_image_urls(item))
    elif isinstance(value, list):
        for item in value:
            if _is_data_image(item):
                images.append(str(item).strip())
            elif isinstance(item, (dict, list)):
                images.extend(_extract_image_urls(item))
    return images


def _content_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    content = payload.get("content")
    if isinstance(content, list):
        return content

    blocks: list[dict[str, Any]] = []
    text = _normalize_compact_text(payload.get("message") or payload.get("text"))
    if text and not _is_data_image(text):
        blocks.append({"type": "text", "text": text})

    seen_images: set[str] = set()
    for image_url in _extract_image_urls(payload):
        if image_url in seen_images:
            continue
        seen_images.add(image_url)
        blocks.append({"type": "input_image", "image_url": image_url})

    return blocks


def _event_payload_to_record(
    payload: dict[str, Any],
    *,
    source_name: str,
    row_index: int,
    current_turn_id: str,
) -> tuple[dict[str, Any] | None, str]:
    source_path = Path(source_name)
    event_type = _normalize_compact_text(
        payload.get("type") or payload.get("kind") or payload.get("event_type") or payload.get("event_name")
    )

    if event_type:
        normalized_payload = dict(payload)
        normalized_payload["type"] = event_type
        if "created_at" in normalized_payload and "timestamp" not in normalized_payload:
            normalized_payload["timestamp"] = normalized_payload["created_at"]
        content_blocks = _content_from_payload(normalized_payload)
        if content_blocks:
            normalized_payload.setdefault("content", content_blocks)
        record, next_turn_id = _event_msg_to_record(
            normalized_payload,
            source_path=source_path,
            line_no=row_index,
            current_turn_id=current_turn_id,
        )
        if record is not None:
            return record, next_turn_id

    if event_type in {"message", "response_item"} or "role" in payload:
        response_payload = dict(payload)
        response_payload["type"] = "message"
        content_blocks = _content_from_payload(response_payload)
        if content_blocks:
            response_payload["content"] = content_blocks
        text = _message_text(response_payload.get("content") or response_payload.get("message") or response_payload.get("text"))
        if text:
            response_payload.setdefault("content", content_blocks or text)
            return _response_item_to_record(
                response_payload,
                source_path=source_path,
                line_no=row_index,
                current_turn_id=current_turn_id,
            )

    text = _best_text(payload)
    content_blocks = _content_from_payload(payload)
    if not text and not content_blocks:
        return None, current_turn_id

    role = _normalize_compact_text(payload.get("role"))
    if role == "user":
        kind = "user_message"
    elif role == "assistant":
        kind = "assistant_message"
    elif "tool" in event_type or "function" in event_type:
        kind = "tool_result" if any(part in event_type for part in ("result", "output", "end")) else "tool_call"
    else:
        kind = "assistant_message"

    turn_id = _normalize_compact_text(payload.get("turn_id")) or current_turn_id
    created_at = _normalize_compact_text(payload.get("created_at") or payload.get("timestamp") or payload.get("time"))
    record = {
        "id": f"{source_path.stem}-{row_index}-{kind}",
        "namespace": source_path.stem,
        "session_id": _normalize_compact_text(payload.get("session_id")) or source_path.stem,
        "thread_id": _normalize_compact_text(payload.get("thread_id") or payload.get("conversation_id")) or source_path.stem,
        "turn_id": turn_id,
        "kind": kind,
        "role": role or ("tool" if kind.startswith("tool_") else None),
        "name": _normalize_compact_text(payload.get("name") or payload.get("tool") or event_type) or None,
        "text": text or _message_text(content_blocks),
        "created_at": created_at,
        "source": {"kind": event_type or "turn_event", "path": source_name, "line": row_index},
        "payload": {**payload, "content": content_blocks} if content_blocks else payload,
    }
    return record, turn_id


def _score_table(table: str, columns: list[str]) -> int:
    table_lower = table.lower()
    column_lowers = {column.lower() for column in columns}
    score = 0
    if any(hint in table_lower for hint in EVENT_TABLE_HINTS):
        score += 5
    if any(column in column_lowers for column in TYPE_COLUMNS):
        score += 4
    if any(column in column_lowers for column in JSON_COLUMNS):
        score += 4
    if any(column in column_lowers for column in THREAD_COLUMNS):
        score += 2
    if any(column in column_lowers for column in TURN_COLUMNS):
        score += 2
    if any(column in column_lowers for column in CREATED_COLUMNS):
        score += 2
    return score


def discover_event_tables(connection: sqlite3.Connection) -> list[tuple[str, list[str], int]]:
    candidates: list[tuple[str, list[str], int]] = []
    for table in _table_names(connection):
        columns = _table_columns(connection, table)
        score = _score_table(table, columns)
        if score > 0:
            candidates.append((table, columns, score))
    return sorted(candidates, key=lambda item: (-item[2], item[0]))


def _where_clause(
    columns: list[str],
    *,
    thread_id: str | None,
    since: str | None,
    until: str | None,
) -> tuple[str, list[Any]]:
    terms: list[str] = []
    params: list[Any] = []
    thread_col = _first_column(columns, THREAD_COLUMNS)
    created_col = _first_column(columns, CREATED_COLUMNS)
    if thread_id and thread_col:
        terms.append(f"{_quote_ident(thread_col)} = ?")
        params.append(thread_id)
    if since and created_col:
        terms.append(f"{_quote_ident(created_col)} >= ?")
        params.append(since)
    if until and created_col:
        terms.append(f"{_quote_ident(created_col)} <= ?")
        params.append(until)
    if not terms:
        return "", params
    return " WHERE " + " AND ".join(terms), params


def _select_sql(
    table: str,
    columns: list[str],
    *,
    limit: int | None,
    thread_id: str | None,
    since: str | None,
    until: str | None,
) -> tuple[str, list[Any]]:
    created_col = _first_column(columns, CREATED_COLUMNS)
    order_cols = [created_col] if created_col else []
    sequence_col = _first_column(columns, ("sequence", "seq", "index", "idx"))
    if sequence_col:
        order_cols.append(sequence_col)
    order_cols.append("rowid")
    where_sql, params = _where_clause(columns, thread_id=thread_id, since=since, until=until)
    order_sql = ", ".join(_quote_ident(column) for column in order_cols)
    sql = f"SELECT rowid AS __rowid__, * FROM {_quote_ident(table)}{where_sql} ORDER BY {order_sql}"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return sql, params


def _row_to_record(
    row: sqlite3.Row,
    *,
    table: str,
    columns: list[str],
    row_index: int,
    current_turn_id: str,
) -> tuple[dict[str, Any] | None, str]:
    row_dict = {key: row[key] for key in row.keys() if key != "__rowid__"}
    type_col = _first_column(columns, TYPE_COLUMNS)
    text_col = _first_column(columns, TEXT_COLUMNS)
    payload = _build_payload(row_dict, type_col, text_col)

    for target, candidates in (
        ("thread_id", THREAD_COLUMNS),
        ("turn_id", TURN_COLUMNS),
        ("created_at", CREATED_COLUMNS),
    ):
        column = _first_column(columns, candidates)
        if column and _normalize_compact_text(row_dict.get(column)):
            payload[target] = row_dict[column]

    return _event_payload_to_record(
        payload,
        source_name=f"{table}.sqlite",
        row_index=row_index,
        current_turn_id=current_turn_id,
    )


def load_turn_event_entries(
    db_path: Path,
    *,
    table: str | None = None,
    limit: int | None = None,
    thread_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with _connect(db_path) as connection:
        tables = discover_event_tables(connection)
        selected_table = table or (tables[0][0] if tables else None)
        if selected_table is None:
            return [], {"tables": [], "selected_table": None}
        columns = _table_columns(connection, selected_table)
        score = _score_table(selected_table, columns)
        sql, params = _select_sql(
            selected_table,
            columns,
            limit=limit,
            thread_id=thread_id,
            since=since,
            until=until,
        )
        records: list[dict[str, Any]] = []
        current_turn_id = selected_table
        for row_index, row in enumerate(connection.execute(sql, params), start=1):
            record, current_turn_id = _row_to_record(
                row,
                table=selected_table,
                columns=columns,
                row_index=row_index,
                current_turn_id=current_turn_id,
            )
            if record is not None:
                records.append(record)

    discovery = {
        "tables": [
            {"name": name, "score": table_score, "columns": table_columns}
            for name, table_columns, table_score in tables
        ],
        "selected_table": selected_table,
        "selected_table_score": score,
        "selected_columns": columns,
        "records_loaded": len(records),
    }
    return _group_records(selected_table, records), discovery


def _group_records(thread_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups_by_turn: dict[tuple[str, str], list[dict[str, Any]]] = {}
    fallback_groups: list[list[dict[str, Any]]] = []
    fallback_current: list[dict[str, Any]] = []

    for record_index, record in enumerate(records, start=1):
        if str(record.get("kind") or "") in {"context", "warning", "error"}:
            continue
        actual_thread_id = _normalize_compact_text(record.get("thread_id")) or thread_id
        turn_id = _normalize_compact_text(record.get("turn_id"))
        if turn_id and turn_id != thread_id:
            groups_by_turn.setdefault((actual_thread_id, turn_id), []).append(record)
            continue

        if str(record.get("kind") or "") == "user_message":
            if fallback_current:
                fallback_groups.append(fallback_current)
            fallback_current = [record]
        elif fallback_current:
            fallback_current.append(record)
        else:
            fallback_current = [record]
            record["turn_id"] = f"{thread_id}-ungrouped-{record_index}"

    if fallback_current:
        fallback_groups.append(fallback_current)

    entries: list[dict[str, Any]] = []
    all_groups = list(groups_by_turn.values()) + fallback_groups
    for index, group in enumerate(all_groups, start=1):
        turn_id = _normalize_compact_text(group[0].get("turn_id")) or f"{thread_id}-turn-{index}"
        actual_thread_id = _normalize_compact_text(group[0].get("thread_id")) or thread_id
        summary = ""
        for record in group:
            if record.get("kind") == "user_message":
                summary = _normalize_compact_text(record.get("text"))
                break
        if not summary:
            summary = _normalize_compact_text(group[0].get("text"))
        entries.append(
            {
                "id": f"{actual_thread_id}:{turn_id}:{index}",
                "entry_type": "turn_card",
                "created_at": _normalize_compact_text(group[0].get("created_at")),
                "title": summary,
                "summary": summary,
                "records": group,
                "turn_id": turn_id,
                "thread_id": actual_thread_id,
                "thread_order": _normalize_compact_text(group[0].get("created_at")) or actual_thread_id,
                "record_count": len(group),
                "card_index": index,
            }
        )
    return entries


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile frames from turn events stored in a SQLite database.")
    parser.add_argument(
        "--input-db",
        type=Path,
        default=DEFAULT_INPUT_DB,
        help="SQLite database containing turn events.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Output directory for rendered frame images.",
    )
    parser.add_argument(
        "--font-path",
        type=Path,
        default=DEFAULT_FONT,
        help="Mono font used for the frame renderer.",
    )
    parser.add_argument("--namespace", default="betterclaw_turn_events", help="Output namespace.")
    parser.add_argument("--table", help="SQLite table to read. Defaults to the best-scored event-like table.")
    parser.add_argument("--limit", type=int, help="Maximum number of database rows to read.")
    parser.add_argument(
        "--thread-id",
        help="Filter by thread/conversation/session id when the selected table has such a column.",
    )
    parser.add_argument("--since", help="Filter by created/timestamp column when present.")
    parser.add_argument("--until", help="Filter by created/timestamp column when present.")
    parser.add_argument("--print-schema", action="store_true", help="Print discovered event-like tables and exit.")
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
    db_path = args.input_db.expanduser().resolve()
    if args.print_schema:
        with _connect(db_path) as connection:
            tables = discover_event_tables(connection)
        print(
            json.dumps(
                [{"name": name, "score": score, "columns": columns} for name, columns, score in tables],
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    cfg = LayoutConfig(compact_tool_details=args.compact_tool_details)
    entries, discovery = load_turn_event_entries(
        db_path,
        table=args.table,
        limit=args.limit,
        thread_id=args.thread_id,
        since=args.since,
        until=args.until,
    )
    summary = compile_entries(
        entries,
        args.output_root,
        cfg,
        args.font_path,
        namespace=args.namespace,
        input_source_path=str(db_path),
        threads_compiled=len({entry.get("thread_id") for entry in entries}),
    )
    summary["discovery"] = discovery
    print(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
