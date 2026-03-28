use crate::storage::{build_memory_item, default_db_path, Db};
use crate::types::{Command, ErrorCode, Request, Response};
use anyhow::{Context, Result};
use serde::Deserialize;
use serde_json::Value;
use std::io::{BufRead, Write};
use tracing::{debug, error, info};

pub struct Protocol;

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

        let mut buffer = String::new();
        let mut handle = stdin.lock();

        match handle.read_line(&mut buffer) {
            Ok(0) => {
                info!("No input received, exiting");
                return Ok(());
            }
            Ok(_) => {}
            Err(e) => {
                error!(error = %e, "Failed to read from stdin");
                eprintln!("Error reading stdin: {}", e);
                std::process::exit(1);
            }
        }

        debug!(input = %buffer, "Received request");

        let request: Request = match serde_json::from_str(&buffer) {
            Ok(req) => req,
            Err(e) => {
                error!(error = %e, "Failed to parse request");
                let response = Response::err(
                    String::new(),
                    format!("Invalid JSON: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
                let _ = serde_json::to_writer(&mut stdout, &response);
                let _ = stdout.flush();
                return Ok(());
            }
        };

        let db = Db::open_default()
            .await
            .context("failed to open database")?;
        let response = Self::handle_request(request, &db).await;

        let output = serde_json::to_string(&response)
            .map_err(|e| anyhow::anyhow!("Failed to serialize response: {}", e))?;

        stdout
            .write_all(output.as_bytes())
            .context("Failed to write response")?;
        stdout.flush().context("Failed to flush output")?;

        debug!(response = %output, "Sent response");
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
