use crate::storage::{
    build_fts_query, build_memory_item, default_db_path, expand_query_terms, normalize_text,
    tokenize_terms, Db,
};
use crate::types::{Command, ErrorCode, Request, Response};
use anyhow::{Context, Result};
use aisdk::core::embedding_model::{EmbeddingModel, EmbeddingModelOptions, EmbeddingModelResponse};
use aisdk::core::DynamicModel;
use aisdk::Result as AisdkResult;
use aisdk::providers::{Google, OpenAI, OpenAICompatible};
use async_trait::async_trait;
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
}

#[derive(Debug, Deserialize)]
struct LedgerListPayload {
    #[serde(default)]
    namespace: Option<String>,
    #[serde(default)]
    thread_id: Option<String>,
    #[serde(default = "default_limit")]
    limit: usize,
}

#[derive(Debug, Deserialize)]
struct LedgerSearchPayload {
    #[serde(default)]
    namespace: Option<String>,
    query: String,
    #[serde(default)]
    query_embedding: Option<Vec<f32>>,
    #[serde(default)]
    thread_id: Option<String>,
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
    #[serde(default)]
    embed: bool,
    #[serde(default)]
    embedding_provider: Option<EmbeddingProviderPayload>,
    entries: Vec<IndexEntryPayload>,
}

#[derive(Debug, Deserialize)]
struct EmbeddingProviderPayload {
    provider: String,
    model: String,
    #[serde(default)]
    base_url: Option<String>,
    #[serde(default)]
    api_key: Option<String>,
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
            None,
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
            .recall_memory(&ns, &parsed.query, parsed.limit)
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
            "SELECT m.id, m.entry_type, m.thread_id, m.turn_id, m.source_type, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.updated_at
             FROM ledger_entries m
             JOIN ledger_entry_chunks t ON t.entry_id = m.id
             WHERE m.namespace_id = ? AND m.deleted_at IS NULL AND m.entry_type IN ('user_turn', 'assistant_turn', 'tool_result')",
        );
        if parsed.thread_id.is_some() {
            sql.push_str(" AND m.thread_id = ?");
        }
        sql.push_str(" ORDER BY m.updated_at DESC LIMIT ?");
        let mut stmt = match conn.prepare(&sql).await {
            Ok(stmt) => stmt,
            Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        };
        let ns_param = ns.clone();
        let rows = match parsed.thread_id.as_ref() {
            Some(thread_id) => {
                stmt.query(libsql::params![ns_param.clone(), thread_id.clone(), parsed.limit as i64]).await
            }
            None => stmt.query(libsql::params![ns_param.clone(), parsed.limit as i64]).await,
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
                "thread_id": row.get::<Option<String>>(2).unwrap_or(None),
                "turn_id": row.get::<Option<String>>(3).unwrap_or(None),
                "created_at": row.get::<String>(8).unwrap_or_default(),
                "citation": row.get::<Option<String>>(7).unwrap_or(None),
                "summary": row.get::<String>(6).unwrap_or_default(),
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
        let limit = parsed.limit as i64;
        let query_embedding = parsed.query_embedding.as_ref().map(|vec| serde_json::to_string(vec).unwrap());
        let mut entries = Vec::new();

        if let Some(query_embedding) = query_embedding {
            let mut sql = String::from(
                "SELECT m.id, m.entry_type, m.thread_id, m.turn_id, m.source_type, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.updated_at, vector_distance_cos(e.embedding, vector(?)) AS rank
                 FROM ledger_entry_embeddings e
                 JOIN ledger_entry_chunks t ON t.chunk_id = e.chunk_id
                 JOIN ledger_entries m ON m.id = t.entry_id
                 WHERE e.namespace_id = ? AND m.namespace_id = ? AND m.deleted_at IS NULL AND m.entry_type IN ('user_turn', 'assistant_turn', 'tool_result')",
            );
            if parsed.thread_id.is_some() {
                sql.push_str(" AND m.thread_id = ?");
            }
            sql.push_str(" ORDER BY rank ASC, m.updated_at DESC LIMIT ?");
            let mut stmt = match conn.prepare(&sql).await {
                Ok(stmt) => stmt,
                Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
            };
            let rows = match parsed.thread_id.as_ref() {
                Some(thread_id) => stmt.query(libsql::params![query_embedding, ns.clone(), ns.clone(), thread_id.clone(), limit]).await,
                None => stmt.query(libsql::params![query_embedding, ns.clone(), ns.clone(), limit]).await,
            };
            let mut rows: libsql::Rows = match rows {
                Ok(rows) => rows,
                Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
            };
            while let Some(row) = match rows.next().await {
                Ok(row) => row,
                Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
            } {
                entries.push(serde_json::json!({
                    "entry_id": row.get::<String>(0).unwrap_or_default(),
                    "thread_id": row.get::<Option<String>>(2).unwrap_or(None),
                    "turn_id": row.get::<Option<String>>(3).unwrap_or(None),
                    "source_type": row.get::<String>(4).unwrap_or_default(),
                    "source_id": row.get::<String>(5).unwrap_or_default(),
                    "created_at": row.get::<String>(8).unwrap_or_default(),
                    "citation": row.get::<Option<String>>(7).unwrap_or(None),
                    "summary": row.get::<String>(6).unwrap_or_default(),
                    "content": row.get::<String>(6).unwrap_or_default(),
                    "score": row.get::<f64>(9).unwrap_or_default(),
                    "matched_chunk": row.get::<String>(6).unwrap_or_default(),
                }));
            }
        } else {
            let normalized_query = normalize_text(&parsed.query);
            let query_terms = tokenize_terms(&normalized_query);
            let expanded_terms = expand_query_terms(&query_terms);
            let fts_query = build_fts_query(&expanded_terms);
            let mut sql = String::from(
                "SELECT m.id, m.entry_type, m.thread_id, m.turn_id, m.source_type, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.updated_at, bm25(ledger_entry_chunks_fts) AS rank
                 FROM ledger_entry_chunks_fts
                 JOIN ledger_entry_chunks t ON t.chunk_id = ledger_entry_chunks_fts.chunk_id
                 JOIN ledger_entries m ON m.id = t.entry_id
                 WHERE ledger_entry_chunks_fts MATCH ? AND ledger_entry_chunks_fts.namespace_id = ? AND m.deleted_at IS NULL AND m.entry_type IN ('user_turn', 'assistant_turn', 'tool_result')",
            );
            if parsed.thread_id.is_some() {
                sql.push_str(" AND m.thread_id = ?");
            }
            sql.push_str(" ORDER BY rank ASC, m.updated_at DESC LIMIT ?");
            let mut stmt = match conn.prepare(&sql).await {
                Ok(stmt) => stmt,
                Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
            };
            let rows = match parsed.thread_id.as_ref() {
                Some(thread_id) => stmt.query(libsql::params![fts_query, ns.clone(), thread_id.clone(), limit]).await,
                None => stmt.query(libsql::params![fts_query, ns.clone(), limit]).await,
            };
            let mut rows: libsql::Rows = match rows {
                Ok(rows) => rows,
                Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
            };
            while let Some(row) = match rows.next().await {
                Ok(row) => row,
                Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
            } {
                entries.push(serde_json::json!({
                    "entry_id": row.get::<String>(0).unwrap_or_default(),
                    "thread_id": row.get::<Option<String>>(2).unwrap_or(None),
                    "turn_id": row.get::<Option<String>>(3).unwrap_or(None),
                    "source_type": row.get::<String>(4).unwrap_or_default(),
                    "source_id": row.get::<String>(5).unwrap_or_default(),
                    "created_at": row.get::<String>(8).unwrap_or_default(),
                    "citation": row.get::<Option<String>>(7).unwrap_or(None),
                    "summary": row.get::<String>(6).unwrap_or_default(),
                    "content": row.get::<String>(6).unwrap_or_default(),
                    "score": row.get::<f64>(9).unwrap_or_default(),
                    "matched_chunk": row.get::<String>(6).unwrap_or_default(),
                }));
            }
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
                "SELECT m.id, m.entry_type, m.thread_id, m.turn_id, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.payload_json, m.updated_at
                 FROM ledger_entries m
                 JOIN ledger_entry_chunks t ON t.entry_id = m.id
                 WHERE m.namespace_id = ? AND m.id = ? AND m.deleted_at IS NULL
                 LIMIT 1",
            )
            .await
        {
            Ok(stmt) => stmt,
            Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        };
        let mut rows: libsql::Rows = match stmt.query(libsql::params![ns.clone(), entry_id.clone()]).await {
            Ok(rows) => rows,
            Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        };
        match rows.next().await {
            Ok(Some(row)) => Response::ok(
                id,
                serde_json::json!({
                    "entry_id": row.get::<String>(0).unwrap_or_default(),
                    "thread_id": row.get::<Option<String>>(2).unwrap_or(None),
                    "turn_id": row.get::<Option<String>>(3).unwrap_or(None),
                    "created_at": row.get::<String>(8).unwrap_or_default(),
                    "citation": row.get::<Option<String>>(6).unwrap_or(None),
                    "content": row.get::<String>(5).unwrap_or_default(),
                    "payload": row.get::<String>(7).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()),
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
        let embeddings = if parsed.embed {
            match embed_entries(parsed.embedding_provider.as_ref(), &parsed.entries).await {
                Ok(embeddings) => embeddings,
                Err(e) => {
                    debug!(error = %e, "embedding generation failed; continuing with FTS only");
                    vec![None; parsed.entries.len()]
                }
            }
        } else {
            vec![None; parsed.entries.len()]
        };
        for (entry, embedding) in parsed.entries.into_iter().zip(embeddings.into_iter()) {
            let entry_type = entry.source_type.clone();
            let summary = Some(entry.content.clone());
            let (item, text) = build_memory_item(
                &ns,
                &entry_type,
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
                embedding,
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
        for item_type in ["user_turn", "assistant_turn", "tool_result"] {
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
                "embedding_available": true,
                "vector_available": true,
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

async fn embed_entries(
    provider: Option<&EmbeddingProviderPayload>,
    entries: &[IndexEntryPayload],
) -> Result<Vec<Option<Vec<f32>>>> {
    let Some(provider) = provider else {
        return Ok(vec![None; entries.len()]);
    };
    if provider.provider.trim().is_empty() || provider.model.trim().is_empty() {
        return Ok(vec![None; entries.len()]);
    }
    let api_key = provider.api_key.clone().unwrap_or_default();
    let base_url = provider.base_url.clone().unwrap_or_default();
    if base_url.trim().is_empty() {
        return Ok(vec![None; entries.len()]);
    }

    let model = build_embeddings_model(&provider.provider, &provider.model, &base_url, &api_key)
        .context("failed to build embeddings provider")?;
    let request = EmbeddingModelOptions::builder()
        .input(entries.iter().map(|entry| entry.content.clone()).collect())
        .dimensions(None)
        .build()
        .context("failed to build embedding request")?;
    let response: Vec<Vec<f32>> = model
        .embed(request)
        .await
        .context("embedding request failed")?;
    Ok(response.into_iter().map(Some).collect())
}

#[derive(Debug, Clone)]
enum EmbeddingsProviderModel {
    OpenAI(OpenAI<DynamicModel>),
    Google(Google<DynamicModel>),
    OpenAICompatible(OpenAICompatible<DynamicModel>),
}

#[async_trait]
impl EmbeddingModel for EmbeddingsProviderModel {
    async fn embed(&self, input: EmbeddingModelOptions) -> AisdkResult<EmbeddingModelResponse> {
        match self {
            Self::OpenAI(model) => model.embed(input).await,
            Self::Google(model) => model.embed(input).await,
            Self::OpenAICompatible(model) => model.embed(input).await,
        }
    }
}

fn build_embeddings_model(
    provider_name: &str,
    model_name: &str,
    base_url: &str,
    api_key: &str,
) -> Result<EmbeddingsProviderModel, anyhow::Error> {
    let provider_name = provider_name.trim().to_lowercase();
    match provider_name.as_str() {
        "openai" => Ok(EmbeddingsProviderModel::OpenAI(
            OpenAI::<DynamicModel>::builder()
                .provider_name("openai")
                .model_name(model_name.to_string())
                .base_url(base_url.to_string())
                .api_key(api_key.to_string())
                .build()
                .map_err(|e| anyhow::anyhow!(e))?,
        )),
        "google" | "gemini" => Ok(EmbeddingsProviderModel::Google(
            Google::<DynamicModel>::builder()
                .provider_name("google")
                .model_name(model_name.to_string())
                .base_url(base_url.to_string())
                .api_key(api_key.to_string())
                .build()
                .map_err(|e| anyhow::anyhow!(e))?,
        )),
        "mistral" | "openrouter" => Ok(EmbeddingsProviderModel::OpenAICompatible(
            OpenAICompatible::<DynamicModel>::builder()
                .provider_name(provider_name)
                .model_name(model_name.to_string())
                .base_url(base_url.to_string())
                .api_key(api_key.to_string())
                .build()
                .map_err(|e| anyhow::anyhow!(e))?,
        )),
        _ => Ok(EmbeddingsProviderModel::OpenAICompatible(
            OpenAICompatible::<DynamicModel>::builder()
                .provider_name(provider_name)
                .model_name(model_name.to_string())
                .base_url(base_url.to_string())
                .api_key(api_key.to_string())
                .build()
                .map_err(|e| anyhow::anyhow!(e))?,
        )),
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
                    "source_type": "user_turn",
                    "source_id": "turn-1",
                    "content": "User prefers verbose responses",
                    "metadata": { "thread_id": "thread-1", "turn_id": "turn-1" }
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
                "limit": 5
            }),
        };
        let response = Protocol::handle_request(recall_request, &db).await;
        assert!(matches!(response.status, ResponseStatus::Ok { .. }));
        if let ResponseStatus::Ok { data, .. } = response.status {
            assert_eq!(data["hits"].as_array().unwrap().len(), 1);
        }
    }
}
