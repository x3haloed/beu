use crate::storage::{build_memory_item, default_db_path, Db};
use crate::types::{Command, ErrorCode, Request, Response};
use anyhow::{Context, Result};
use serde::Deserialize;
use serde_json::Value;
use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::sync::{Arc, Mutex, OnceLock};
use tracing::{debug, error, info};
use tokio::sync::Notify;

pub struct Protocol;

static WAIT_REGISTRY: OnceLock<Mutex<HashMap<String, Arc<Notify>>>> = OnceLock::new();

#[derive(Debug, Deserialize)]
struct RecallPayload {
    #[serde(default)]
    namespace: Option<String>,
    query: String,
    #[serde(default = "default_limit")]
    limit: usize,
    #[serde(default)]
    sources: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct LedgerListPayload {
    #[serde(default)]
    namespace: Option<String>,
    #[serde(default)]
    thread_id: Option<String>,
    #[serde(default)]
    kind: Option<String>,
    #[serde(default = "default_limit")]
    limit: usize,
}

#[derive(Debug, Deserialize)]
struct LedgerSearchPayload {
    #[serde(default)]
    namespace: Option<String>,
    query: String,
    #[serde(default)]
    thread_id: Option<String>,
    #[serde(default)]
    kind: Option<String>,
    #[serde(default = "default_limit")]
    limit: usize,
}

#[derive(Debug, Deserialize)]
struct LedgerGetPayload {
    #[serde(default)]
    namespace: Option<String>,
    entry_id: String,
}

#[derive(Debug, Deserialize)]
struct IndexEntryPayload {
    entry_id: String,
    source_type: String,
    source_id: String,
    content: String,
    #[serde(default)]
    metadata: Value,
}

#[derive(Debug, Deserialize)]
struct IndexPayload {
    #[serde(default)]
    namespace: Option<String>,
    entries: Vec<IndexEntryPayload>,
}

#[derive(Debug, Deserialize)]
struct DistillPayload {
    #[serde(default)]
    namespace: Option<String>,
    #[serde(default)]
    facts: Vec<Value>,
    #[serde(default)]
    invariant_adds: Vec<Value>,
    #[serde(default)]
    wake_pack: Option<Value>,
}

#[derive(Debug, Deserialize)]
struct WaitPayload {
    token: String,
}

fn default_limit() -> usize {
    5
}

impl Protocol {
    pub fn run() -> Result<()> {
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .context("failed to build tokio runtime")?;
        rt.block_on(Self::run_async())
    }

    async fn run_async() -> Result<()> {
        let stdin = std::io::stdin();
        let mut stdout = std::io::stdout();
        let db = Arc::new(Db::open_default().await.context("failed to open database")?);
        let (request_tx, mut request_rx) = tokio::sync::mpsc::unbounded_channel::<String>();
        let (response_tx, mut response_rx) = tokio::sync::mpsc::unbounded_channel::<String>();
        let writer = tokio::task::spawn_blocking(move || {
            while let Some(output) = response_rx.blocking_recv() {
                if let Err(e) = stdout.write_all(output.as_bytes()) {
                    error!(error = %e, "Failed to write response");
                    break;
                }
                if let Err(e) = stdout.write_all(b"\n") {
                    error!(error = %e, "Failed to write newline");
                    break;
                }
                if let Err(e) = stdout.flush() {
                    error!(error = %e, "Failed to flush output");
                    break;
                }
            }
        });

        let reader_tx = request_tx.clone();
        let reader = std::thread::spawn(move || {
            let mut handle = stdin.lock();
            let mut buffer = String::new();
            loop {
                buffer.clear();
                match handle.read_line(&mut buffer) {
                    Ok(0) => break,
                    Ok(_) => {
                        let trimmed = buffer.trim();
                        if !trimmed.is_empty() {
                            let _ = reader_tx.send(trimmed.to_string());
                        }
                    }
                    Err(e) => {
                        error!(error = %e, "Failed to read from stdin");
                        break;
                    }
                }
            }
        });
        drop(request_tx);

        let mut tasks = Vec::new();

        while let Some(request_text) = request_rx.recv().await {
            debug!(input = %request_text, "Received request");

            let response_tx = response_tx.clone();
            let db = db.clone();
            tasks.push(tokio::spawn(async move {
                let response = match serde_json::from_str::<Request>(&request_text) {
                    Ok(request) => Self::handle_request(request, &db).await,
                    Err(e) => {
                        error!(error = %e, "Failed to parse request");
                        Response::err(
                            String::new(),
                            format!("Invalid JSON: {}", e),
                            ErrorCode::INVALID_REQUEST,
                        )
                    }
                };

                match serde_json::to_string(&response) {
                    Ok(output) => {
                        let _ = response_tx.send(output);
                    }
                    Err(e) => {
                        error!(error = %e, "Failed to serialize response");
                    }
                }
            }));
        }

        info!("stdin closed, exiting");
        drop(response_tx);
        for task in tasks {
            let _ = task.await;
        }
        let _ = reader.join();
        let _ = writer.await;
        Ok(())
    }

    pub async fn handle_request(request: Request, db: &Db) -> Response {
        let command = match Command::parse(&request.command) {
            Some(cmd) => cmd,
            None => {
                return Response::err(
                    request.id,
                    format!("Unknown command: {}", request.command),
                    ErrorCode::UNKNOWN_COMMAND,
                );
            }
        };

        let namespace = request
            .namespace
            .clone()
            .unwrap_or_else(|| "default".to_string());

        debug!(command = %request.command, namespace = %namespace, id = %request.id, "Handling command");

        match command {
            Command::Distill => {
                Self::handle_distill(request.id, namespace, request.payload, db).await
            }
            Command::Recall => {
                Self::handle_recall(request.id, namespace, request.payload, db).await
            }
            Command::LedgerList => {
                Self::handle_ledger_list(request.id, namespace, request.payload, db).await
            }
            Command::LedgerSearch => {
                Self::handle_ledger_search(request.id, namespace, request.payload, db).await
            }
            Command::LedgerGet => {
                Self::handle_ledger_get(request.id, namespace, request.payload, db).await
            }
            Command::WaitHold => Self::handle_wait_hold(request.id, namespace, request.payload).await,
            Command::WaitRelease => {
                Self::handle_wait_release(request.id, namespace, request.payload).await
            }
            Command::Rebuild => Self::handle_rebuild(request.id, namespace, request.payload).await,
            Command::Identity => {
                Self::handle_identity(request.id, namespace, request.payload).await
            }
            Command::Index => Self::handle_index(request.id, namespace, request.payload, db).await,
            Command::Status => {
                Self::handle_status(request.id, namespace, request.payload, db).await
            }
        }
    }

    async fn handle_distill(id: String, namespace: String, payload: Value, db: &Db) -> Response {
        let parsed: DistillPayload = match serde_json::from_value(payload.clone()) {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Invalid distill payload: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
            }
        };
        let ns = parsed.namespace.unwrap_or(namespace);
        let now_payload = serde_json::json!({
            "facts": parsed.facts,
            "invariant_adds": parsed.invariant_adds,
            "wake_pack": parsed.wake_pack,
        });
        let (item, text) = build_memory_item(
            &ns,
            "wake_pack",
            "distill",
            &id,
            Some("Distilled memory".to_string()),
            Some("Memory distilled from thread history".to_string()),
            Some(id.clone()),
            now_payload,
            10,
        );
        if let Err(e) = db.upsert_memory_item(item, text).await {
            return Response::err(
                id,
                format!("Storage error: {}", e),
                ErrorCode::STORAGE_ERROR,
            );
        }
        Response::ok(
            id,
            serde_json::json!({
                "message": "distill stored",
                "namespace": ns
            }),
        )
    }

    async fn handle_recall(id: String, namespace: String, payload: Value, db: &Db) -> Response {
        let parsed: RecallPayload = match serde_json::from_value(payload) {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Invalid recall payload: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
            }
        };
        let ns = parsed.namespace.unwrap_or(namespace);
        match db
            .recall_memory(&ns, &parsed.query, &parsed.sources, parsed.limit)
            .await
        {
            Ok(hits) => Response::ok(
                id,
                serde_json::json!({
                    "hits": hits.into_iter().map(|hit| serde_json::json!({
                        "source_type": hit.source_type,
                        "source_id": hit.source_id,
                        "content": hit.content,
                        "score": hit.score,
                        "citation": hit.citation,
                    })).collect::<Vec<_>>()
                }),
            ),
            Err(e) => Response::err(
                id,
                format!("Storage error: {}", e),
                ErrorCode::STORAGE_ERROR,
            ),
        }
    }

    async fn handle_ledger_list(id: String, namespace: String, payload: Value, db: &Db) -> Response {
        let parsed: LedgerListPayload = match serde_json::from_value(payload.clone()) {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Invalid ledger_list payload: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
            }
        };
        let ns = parsed.namespace.unwrap_or(namespace);
        let (_guard, conn) = match db.write_connection().await {
            Ok(value) => value,
            Err(e) => {
                return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR);
            }
        };
        let mut sql = String::from(
            "SELECT m.id, m.item_type, m.source_type, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.updated_at
             FROM memory_items m
             JOIN memory_item_text t ON t.item_id = m.id
             WHERE m.namespace_id = ? AND m.deleted_at IS NULL",
        );
        if parsed.thread_id.is_some() {
            sql.push_str(" AND json_extract(m.payload_json, '$.metadata.thread_id') = ?");
        }
        if parsed.kind.is_some() {
            sql.push_str(" AND m.item_type = ?");
        }
        sql.push_str(" ORDER BY m.updated_at DESC LIMIT ?");
        let mut stmt = match conn.prepare(&sql).await {
            Ok(stmt) => stmt,
            Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        };
        let ns_param = ns.clone();
        let rows = match (parsed.thread_id.as_ref(), parsed.kind.as_ref()) {
            (Some(thread_id), Some(kind)) => {
                stmt.query(libsql::params![ns_param.clone(), thread_id.clone(), kind.clone(), parsed.limit as i64]).await
            }
            (Some(thread_id), None) => {
                stmt.query(libsql::params![ns_param.clone(), thread_id.clone(), parsed.limit as i64]).await
            }
            (None, Some(kind)) => {
                stmt.query(libsql::params![ns_param.clone(), kind.clone(), parsed.limit as i64]).await
            }
            (None, None) => stmt.query(libsql::params![ns_param.clone(), parsed.limit as i64]).await,
        };
        let mut rows = match rows {
            Ok(rows) => rows,
            Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        };
        let mut entries = Vec::new();
        while let Some(row) = match rows.next().await {
            Ok(row) => row,
            Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        } {
            entries.push(serde_json::json!({
                "entry_id": row.get::<String>(0).unwrap_or_default(),
                "thread_id": row.get::<String>(3).unwrap_or_default(),
                "turn_id": row.get::<String>(3).unwrap_or_default(),
                "kind": row.get::<String>(1).unwrap_or_default(),
                "created_at": row.get::<String>(6).unwrap_or_default(),
                "citation": row.get::<Option<String>>(5).unwrap_or(None),
                "summary": row.get::<String>(4).unwrap_or_default(),
            }));
        }
        Response::ok(
            id,
            serde_json::json!({
                "entries": entries,
                "entry_count": entries.len(),
                "truncated": false,
                "limit_reached": serde_json::Value::Null,
                "namespace": ns
            }),
        )
    }

    async fn handle_ledger_search(id: String, namespace: String, payload: Value, db: &Db) -> Response {
        let parsed: LedgerSearchPayload = match serde_json::from_value(payload.clone()) {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Invalid ledger_search payload: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
            }
        };
        let ns = parsed.namespace.unwrap_or(namespace);
        let (_guard, conn) = match db.write_connection().await {
            Ok(value) => value,
            Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        };
        let mut sql = String::from(
            "SELECT m.id, m.item_type, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.updated_at, bm25(memory_item_fts) AS rank
             FROM memory_item_fts
             JOIN memory_items m ON m.id = memory_item_fts.item_id
             JOIN memory_item_text t ON t.item_id = m.id
             WHERE memory_item_fts MATCH ? AND memory_item_fts.namespace_id = ? AND m.deleted_at IS NULL",
        );
        if parsed.thread_id.is_some() {
            sql.push_str(" AND json_extract(m.payload_json, '$.metadata.thread_id') = ?");
        }
        if parsed.kind.is_some() {
            sql.push_str(" AND m.item_type = ?");
        }
        sql.push_str(" ORDER BY rank ASC, m.updated_at DESC LIMIT ?");
        let mut stmt = match conn.prepare(&sql).await {
            Ok(stmt) => stmt,
            Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        };
        let query = parsed.query.clone();
        let limit = parsed.limit as i64;
        let rows = match (parsed.thread_id.as_ref(), parsed.kind.as_ref()) {
            (Some(thread_id), Some(kind)) => {
                stmt.query(libsql::params![query, ns.clone(), thread_id.clone(), kind.clone(), limit]).await
            }
            (Some(thread_id), None) => {
                stmt.query(libsql::params![query, ns.clone(), thread_id.clone(), limit]).await
            }
            (None, Some(kind)) => {
                stmt.query(libsql::params![query, ns.clone(), kind.clone(), limit]).await
            }
            (None, None) => stmt.query(libsql::params![query, ns.clone(), limit]).await,
        };
        let mut rows = match rows {
            Ok(rows) => rows,
            Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        };
        let mut entries = Vec::new();
        while let Some(row) = match rows.next().await {
            Ok(row) => row,
            Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        } {
            entries.push(serde_json::json!({
                "entry_id": row.get::<String>(0).unwrap_or_default(),
                "thread_id": ns.clone(),
                "turn_id": row.get::<String>(2).unwrap_or_default(),
                "kind": row.get::<String>(1).unwrap_or_default(),
                "created_at": row.get::<String>(5).unwrap_or_default(),
                "citation": row.get::<Option<String>>(4).unwrap_or(None),
                "summary": row.get::<String>(3).unwrap_or_default(),
                "content": row.get::<String>(3).unwrap_or_default(),
                "score": row.get::<f64>(6).unwrap_or_default(),
                "matched_chunk": row.get::<String>(3).unwrap_or_default(),
            }));
        }
        Response::ok(
            id,
            serde_json::json!({
                "query": parsed.query,
                "entries": entries,
                "entry_count": entries.len(),
                "namespace": ns
            }),
        )
    }

    async fn handle_ledger_get(id: String, namespace: String, payload: Value, db: &Db) -> Response {
        let parsed: LedgerGetPayload = match serde_json::from_value(payload.clone()) {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Invalid ledger_get payload: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
            }
        };
        let ns = parsed.namespace.unwrap_or(namespace);
        let entry_id = parsed.entry_id.clone();
        let (_guard, conn) = match db.write_connection().await {
            Ok(value) => value,
            Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        };
        let mut stmt = match conn
            .prepare(
                "SELECT m.id, m.item_type, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.payload_json, m.updated_at
                 FROM memory_items m
                 JOIN memory_item_text t ON t.item_id = m.id
                 WHERE m.namespace_id = ? AND json_extract(m.payload_json, '$.entry_id') = ? AND m.deleted_at IS NULL
                 LIMIT 1",
            )
            .await
        {
            Ok(stmt) => stmt,
            Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        };
        let mut rows = match stmt.query(libsql::params![ns.clone(), entry_id.clone()]).await {
            Ok(rows) => rows,
            Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        };
        match rows.next().await {
            Ok(Some(row)) => Response::ok(
                id,
                serde_json::json!({
                    "entry_id": row.get::<String>(0).unwrap_or_default(),
                    "thread_id": ns,
                    "turn_id": row.get::<String>(2).unwrap_or_default(),
                    "kind": row.get::<String>(1).unwrap_or_default(),
                    "created_at": row.get::<String>(6).unwrap_or_default(),
                    "citation": row.get::<Option<String>>(4).unwrap_or(None),
                    "content": row.get::<String>(3).unwrap_or_default(),
                    "payload": row.get::<String>(5).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()),
                }),
            ),
            Ok(None) => Response::err(
                id,
                format!("ledger entry not found: {}", entry_id),
                ErrorCode::NOT_FOUND,
            ),
            Err(e) => Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        }
    }

    async fn handle_rebuild(id: String, namespace: String, _payload: Value) -> Response {
        Response::ok(
            id,
            serde_json::json!({
                "message": "rebuild not yet implemented",
                "namespace": namespace
            }),
        )
    }

    async fn handle_identity(id: String, namespace: String, _payload: Value) -> Response {
        Response::ok(
            id,
            serde_json::json!({
                "message": "identity not yet implemented",
                "namespace": namespace
            }),
        )
    }

    async fn handle_index(id: String, namespace: String, payload: Value, db: &Db) -> Response {
        let parsed: IndexPayload = match serde_json::from_value(payload) {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Invalid index payload: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
            }
        };
        let ns = parsed.namespace.unwrap_or(namespace);
        let mut indexed = 0usize;
        for entry in parsed.entries {
            let item_type = entry
                .metadata
                .get("kind")
                .and_then(Value::as_str)
                .unwrap_or("fact");
            let summary = Some(entry.content.clone());
            let (item, text) = build_memory_item(
                &ns,
                item_type,
                &entry.source_type,
                &entry.source_id,
                Some(entry.entry_id.clone()),
                summary,
                Some(entry.entry_id.clone()),
                serde_json::json!({
                    "entry_id": entry.entry_id,
                    "content": entry.content,
                    "metadata": entry.metadata,
                }),
                5,
            );
            if let Err(e) = db.upsert_memory_item(item, text).await {
                return Response::err(
                    id,
                    format!("Storage error: {}", e),
                    ErrorCode::STORAGE_ERROR,
                );
            }
            indexed += 1;
        }
        Response::ok(
            id,
            serde_json::json!({
                "indexed": indexed,
                "namespace": ns
            }),
        )
    }

    async fn handle_status(id: String, namespace: String, _payload: Value, db: &Db) -> Response {
        let mut counts = serde_json::Map::new();
        for item_type in ["invariant", "fact", "wake_pack", "identity", "drift_item"] {
            let count = db
                .count_memory_items(&namespace, item_type)
                .await
                .unwrap_or(0);
            counts.insert(item_type.to_string(), serde_json::json!(count));
        }
        Response::ok(
            id,
            serde_json::json!({
                "storage": "ok",
                "embedding_available": false,
                "vector_available": false,
                "fts_available": true,
                "counts": counts,
                "db_path": default_db_path().map(|p| p.display().to_string()),
                "namespace": namespace
            }),
        )
    }

    async fn handle_wait_hold(id: String, namespace: String, payload: Value) -> Response {
        let parsed: WaitPayload = match serde_json::from_value(payload) {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Invalid wait_hold payload: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
            }
        };
        let notify = {
            let registry = WAIT_REGISTRY.get_or_init(|| Mutex::new(HashMap::new()));
            let mut guard = registry.lock().expect("wait registry lock");
            guard
                .entry(parsed.token.clone())
                .or_insert_with(|| Arc::new(Notify::new()))
                .clone()
        };
        notify.notified().await;
        Response::ok(
            id,
            serde_json::json!({
                "message": "wait released",
                "token": parsed.token,
                "namespace": namespace
            }),
        )
    }

    async fn handle_wait_release(id: String, namespace: String, payload: Value) -> Response {
        let parsed: WaitPayload = match serde_json::from_value(payload) {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Invalid wait_release payload: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
            }
        };
        let notify = {
            let registry = WAIT_REGISTRY.get_or_init(|| Mutex::new(HashMap::new()));
            let mut guard = registry.lock().expect("wait registry lock");
            guard.remove(&parsed.token)
        };
        match notify {
            Some(notify) => {
                notify.notify_waiters();
                Response::ok(
                    id,
                    serde_json::json!({
                        "message": "wait released",
                        "token": parsed.token,
                        "namespace": namespace
                    }),
                )
            }
            None => Response::err(
                id,
                format!("wait token not found: {}", parsed.token),
                ErrorCode::NOT_FOUND,
            ),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::Db;
    use crate::types::ResponseStatus;

    async fn new_db() -> Db {
        Db::open_in_memory().await.unwrap()
    }

    #[tokio::test]
    async fn test_valid_request_status() {
        let db = new_db().await;
        let request = Request {
            version: "1.0.0".to_string(),
            command: "status".to_string(),
            id: "test-123".to_string(),
            namespace: Some("default".to_string()),
            payload: serde_json::json!({}),
        };

        let response = Protocol::handle_request(request, &db).await;

        assert!(matches!(response.status, ResponseStatus::Ok { .. }));
        if let ResponseStatus::Ok { data, .. } = response.status {
            assert_eq!(data["storage"], "ok");
            assert_eq!(data["fts_available"], true);
        }
    }

    #[tokio::test]
    async fn test_valid_request_distill() {
        let db = new_db().await;
        let request = Request {
            version: "1.0.0".to_string(),
            command: "distill".to_string(),
            id: "test-456".to_string(),
            namespace: None,
            payload: serde_json::json!({
                "facts": [{"claim": "User prefers detailed explanations"}],
                "invariant_adds": [{"claim": "User prefers detailed explanations"}],
                "wake_pack": {"content": "User prefers detailed explanations"}
            }),
        };

        let response = Protocol::handle_request(request, &db).await;

        assert!(matches!(response.status, ResponseStatus::Ok { .. }));
        if let ResponseStatus::Ok { data, .. } = response.status {
            assert_eq!(data["message"], "distill stored");
            assert_eq!(data["namespace"], "default");
        }
    }

    #[tokio::test]
    async fn test_unknown_command() {
        let db = new_db().await;
        let request = Request {
            version: "1.0.0".to_string(),
            command: "invalid_cmd".to_string(),
            id: "test-789".to_string(),
            namespace: None,
            payload: serde_json::json!({}),
        };

        let response = Protocol::handle_request(request, &db).await;

        assert!(matches!(response.status, ResponseStatus::Err { .. }));
        if let ResponseStatus::Err { error, code, .. } = response.status {
            assert!(error.contains("Unknown command"));
            assert_eq!(code, "UNKNOWN_COMMAND");
        }
    }

    #[tokio::test]
    async fn test_all_commands() {
        let db = new_db().await;
        for cmd in [
            "distill", "recall", "rebuild", "identity", "index", "status",
        ] {
            let payload = match cmd {
                "recall" => serde_json::json!({ "query": "test", "limit": 1 }),
                "index" => serde_json::json!({ "entries": [] }),
                "distill" => serde_json::json!({}),
                _ => serde_json::json!({}),
            };
            let request = Request {
                version: "1.0.0".to_string(),
                command: cmd.to_string(),
                id: "test".to_string(),
                namespace: None,
                payload,
            };
            let response = Protocol::handle_request(request, &db).await;
            assert!(
                matches!(response.status, ResponseStatus::Ok { .. }),
                "Command {cmd} should succeed"
            );
        }
    }

    #[tokio::test]
    async fn test_custom_namespace() {
        let db = new_db().await;
        let request = Request {
            version: "1.0.0".to_string(),
            command: "status".to_string(),
            id: "test".to_string(),
            namespace: Some("agent-123".to_string()),
            payload: serde_json::json!({}),
        };

        let response = Protocol::handle_request(request, &db).await;

        assert!(matches!(response.status, ResponseStatus::Ok { .. }));
        if let ResponseStatus::Ok { data, .. } = response.status {
            assert_eq!(data["namespace"], "agent-123");
        }
    }

    #[tokio::test]
    async fn test_response_serialization() {
        let db = new_db().await;
        let request = Request {
            version: "1.0.0".to_string(),
            command: "status".to_string(),
            id: "test-abc".to_string(),
            namespace: None,
            payload: serde_json::json!({}),
        };

        let response = Protocol::handle_request(request, &db).await;
        let json = serde_json::to_string(&response).unwrap();

        assert!(json.contains(r#""version":"1.0.0"#));
        assert!(json.contains(r#""id":"test-abc""#));
        assert!(json.contains(r#""ok":true"#));
    }

    #[tokio::test]
    async fn test_recall_after_index() {
        let db = new_db().await;
        let index_request = Request {
            version: "1.0.0".to_string(),
            command: "index".to_string(),
            id: "idx-1".to_string(),
            namespace: Some("default".to_string()),
            payload: serde_json::json!({
                "entries": [{
                    "entry_id": "entry-1",
                    "source_type": "ledger_entry",
                    "source_id": "turn-1",
                    "content": "User prefers verbose responses",
                    "metadata": { "kind": "invariant" }
                }]
            }),
        };
        assert!(matches!(
            Protocol::handle_request(index_request, &db).await.status,
            ResponseStatus::Ok { .. }
        ));

        let recall_request = Request {
            version: "1.0.0".to_string(),
            command: "recall".to_string(),
            id: "rec-1".to_string(),
            namespace: Some("default".to_string()),
            payload: serde_json::json!({
                "query": "verbose responses",
                "limit": 5,
                "sources": ["invariant"]
            }),
        };
        let response = Protocol::handle_request(recall_request, &db).await;
        assert!(matches!(response.status, ResponseStatus::Ok { .. }));
        if let ResponseStatus::Ok { data, .. } = response.status {
            assert_eq!(data["hits"].as_array().unwrap().len(), 1);
        }
    }
}
