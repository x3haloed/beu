use crate::types::{Command, ErrorCode, Request, Response};
use anyhow::{Context, Result};
use std::io::{BufRead, Write};
use tracing::{debug, error, info};

pub struct Protocol;

impl Protocol {
    pub fn run() -> Result<()> {
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

        let response = Self::handle_request(request);

        let output = serde_json::to_string(&response)
            .map_err(|e| anyhow::anyhow!("Failed to serialize response: {}", e))?;

        stdout
            .write_all(output.as_bytes())
            .context("Failed to write response")?;
        stdout.flush().context("Failed to flush output")?;

        debug!(response = %output, "Sent response");

        Ok(())
    }

    pub fn handle_request(request: Request) -> Response {
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

        let namespace = request.namespace.unwrap_or_else(|| "default".to_string());

        debug!(command = %request.command, namespace = %namespace, id = %request.id, "Handling command");

        match command {
            Command::Distill => Self::handle_distill(request.id, namespace, request.payload),
            Command::Recall => Self::handle_recall(request.id, namespace, request.payload),
            Command::Rebuild => Self::handle_rebuild(request.id, namespace, request.payload),
            Command::Identity => Self::handle_identity(request.id, namespace, request.payload),
            Command::Index => Self::handle_index(request.id, namespace, request.payload),
            Command::Status => Self::handle_status(request.id, namespace, request.payload),
        }
    }

    pub fn handle_distill(id: String, namespace: String, _payload: serde_json::Value) -> Response {
        Response::ok(
            id,
            serde_json::json!({
                "message": "distill not yet implemented",
                "namespace": namespace
            }),
        )
    }

    pub fn handle_recall(id: String, namespace: String, _payload: serde_json::Value) -> Response {
        Response::ok(
            id,
            serde_json::json!({
                "message": "recall not yet implemented",
                "namespace": namespace
            }),
        )
    }

    pub fn handle_rebuild(id: String, namespace: String, _payload: serde_json::Value) -> Response {
        Response::ok(
            id,
            serde_json::json!({
                "message": "rebuild not yet implemented",
                "namespace": namespace
            }),
        )
    }

    pub fn handle_identity(id: String, namespace: String, _payload: serde_json::Value) -> Response {
        Response::ok(
            id,
            serde_json::json!({
                "message": "identity not yet implemented",
                "namespace": namespace
            }),
        )
    }

    pub fn handle_index(id: String, namespace: String, _payload: serde_json::Value) -> Response {
        Response::ok(
            id,
            serde_json::json!({
                "message": "index not yet implemented",
                "namespace": namespace
            }),
        )
    }

    pub fn handle_status(id: String, namespace: String, _payload: serde_json::Value) -> Response {
        Response::ok(
            id,
            serde_json::json!({
                "message": "status not yet implemented",
                "namespace": namespace
            }),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::ResponseStatus;

    #[test]
    fn test_valid_request_status() {
        let request = Request {
            version: "1.0.0".to_string(),
            command: "status".to_string(),
            id: "test-123".to_string(),
            namespace: Some("default".to_string()),
            payload: serde_json::json!({}),
        };

        let response = Protocol::handle_request(request);

        assert!(matches!(response.status, ResponseStatus::Ok { .. }));
        if let ResponseStatus::Ok { data, .. } = response.status {
            assert_eq!(data["message"], "status not yet implemented");
        }
    }

    #[test]
    fn test_valid_request_distill() {
        let request = Request {
            version: "1.0.0".to_string(),
            command: "distill".to_string(),
            id: "test-456".to_string(),
            namespace: None,
            payload: serde_json::json!({}),
        };

        let response = Protocol::handle_request(request);

        assert!(matches!(response.status, ResponseStatus::Ok { .. }));
        if let ResponseStatus::Ok { data, .. } = response.status {
            assert_eq!(data["message"], "distill not yet implemented");
            assert_eq!(data["namespace"], "default");
        }
    }

    #[test]
    fn test_unknown_command() {
        let request = Request {
            version: "1.0.0".to_string(),
            command: "invalid_cmd".to_string(),
            id: "test-789".to_string(),
            namespace: None,
            payload: serde_json::json!({}),
        };

        let response = Protocol::handle_request(request);

        assert!(matches!(response.status, ResponseStatus::Err { .. }));
        if let ResponseStatus::Err { error, code, .. } = response.status {
            assert!(error.contains("Unknown command"));
            assert_eq!(code, "UNKNOWN_COMMAND");
        } else {
            panic!("Expected error response");
        }
    }

    #[test]
    fn test_all_commands() {
        let commands = vec![
            "distill", "recall", "rebuild", "identity", "index", "status",
        ];

        for cmd in commands {
            let request = Request {
                version: "1.0.0".to_string(),
                command: cmd.to_string(),
                id: "test".to_string(),
                namespace: None,
                payload: serde_json::json!({}),
            };

            let response = Protocol::handle_request(request);
            assert!(
                matches!(response.status, ResponseStatus::Ok { .. }),
                "Command {} should succeed",
                cmd
            );
        }
    }

    #[test]
    fn test_custom_namespace() {
        let request = Request {
            version: "1.0.0".to_string(),
            command: "status".to_string(),
            id: "test".to_string(),
            namespace: Some("agent-123".to_string()),
            payload: serde_json::json!({}),
        };

        let response = Protocol::handle_request(request);

        assert!(matches!(response.status, ResponseStatus::Ok { .. }));
        if let ResponseStatus::Ok { data, .. } = response.status {
            assert_eq!(data["namespace"], "agent-123");
        }
    }

    #[test]
    fn test_response_serialization() {
        let request = Request {
            version: "1.0.0".to_string(),
            command: "status".to_string(),
            id: "test-abc".to_string(),
            namespace: None,
            payload: serde_json::json!({}),
        };

        let response = Protocol::handle_request(request);
        let json = serde_json::to_string(&response).unwrap();

        assert!(json.contains(r#""version":"1.0.0"#));
        assert!(json.contains(r#""id":"test-abc""#));
        assert!(json.contains(r#""ok":true"#));
    }
}
