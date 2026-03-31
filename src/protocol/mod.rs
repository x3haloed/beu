use crate::storage::{
    build_fts_query, build_memory_item, default_db_path, expand_query_terms, normalize_text,
    tokenize_terms, Db,
};
use crate::types::{Command, ErrorCode, Request, Response};
use anyhow::{Context, Result};
use serde_json::Value;
use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::sync::{Arc, Mutex, OnceLock};
use tokio::sync::Notify;
use tracing::{debug, error, info};

mod distill;
mod distill_tick;
mod index;
mod ledger;
mod recall;
mod shared;
mod status;
mod wait;
use shared::*;

pub struct Protocol;

static WAIT_REGISTRY: OnceLock<Mutex<HashMap<String, Arc<Notify>>>> = OnceLock::new();

impl Protocol {}

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
        let db = Arc::new(
            Db::open_default()
                .await
                .context("failed to open database")?,
        );
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
            Command::WaitHold => {
                Self::handle_wait_hold(request.id, namespace, request.payload).await
            }
            Command::WaitRelease => {
                Self::handle_wait_release(request.id, namespace, request.payload).await
            }
            Command::DistillTick => {
                Self::handle_distill_tick(request.id, namespace, request.payload, db).await
            }
            Command::DistillReset => {
                Self::handle_distill_reset(request.id, namespace, request.payload, db).await
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
    async fn test_distill_requires_provider_metadata() {
        let db = new_db().await;
        let request = Request {
            version: "1.0.0".to_string(),
            command: "distill".to_string(),
            id: "test-456".to_string(),
            namespace: None,
            payload: serde_json::json!({}),
        };

        let response = Protocol::handle_request(request, &db).await;

        assert!(matches!(response.status, ResponseStatus::Err { .. }));
        if let ResponseStatus::Err { error, code, .. } = response.status {
            assert!(!error.is_empty());
            assert_eq!(code, "INVALID_REQUEST");
        }
    }

    #[test]
    fn test_distill_provider_branch_covers_allowed_families() {
        let cases = [
            ("openai", Some("openai")),
            ("google", Some("google")),
            ("gemini", Some("google")),
            ("mistral", Some("openai_compatible")),
            ("openrouter", Some("openai_compatible")),
            ("custom", Some("openai_compatible")),
            ("groq", Some("groq")),
            ("amazon_bedrock", Some("amazon_bedrock")),
            ("togetherai", Some("togetherai")),
            ("xai", Some("xai")),
        ];

        for (provider, expected) in cases {
            assert_eq!(
                Protocol::distill_provider_branch(provider),
                expected,
                "provider {provider}"
            );
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
        for cmd in ["recall", "rebuild", "identity", "index", "status"] {
            let payload = match cmd {
                "recall" => serde_json::json!({ "query": "test", "limit": 1 }),
                "index" => serde_json::json!({ "entries": [] }),
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
