use super::*;
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct DistillTickPayload {
    thread_id: String,
    turn_id: String,
    #[serde(default)]
    event_kind: Option<String>,
}

impl Protocol {
    pub(super) async fn handle_distill_tick(
        id: String,
        namespace: String,
        payload: Value,
        db: &Db,
    ) -> Response {
        let parsed: DistillTickPayload = match serde_json::from_value(payload.clone()) {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Invalid distill_tick payload: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
            }
        };
        let event_kind = parsed.event_kind.as_deref().unwrap_or("hook");
        match db
            .note_distill_hook(&namespace, &parsed.thread_id, &parsed.turn_id, event_kind)
            .await
        {
            Ok(hook_count) => Response::ok(
                id,
                serde_json::json!({
                    "namespace": namespace,
                    "thread_id": parsed.thread_id,
                    "turn_id": parsed.turn_id,
                    "hook_count": hook_count,
                }),
            ),
            Err(e) => Response::err(
                id,
                format!("Storage error: {}", e),
                ErrorCode::STORAGE_ERROR,
            ),
        }
    }

    pub(super) async fn handle_distill_reset(
        id: String,
        namespace: String,
        payload: Value,
        db: &Db,
    ) -> Response {
        let parsed: DistillTickPayload = match serde_json::from_value(payload.clone()) {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Invalid distill_reset payload: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
            }
        };
        match db
            .clear_distill_hook_count(&namespace, &parsed.thread_id)
            .await
        {
            Ok(()) => Response::ok(
                id,
                serde_json::json!({
                    "namespace": namespace,
                    "thread_id": parsed.thread_id,
                    "turn_id": parsed.turn_id,
                }),
            ),
            Err(e) => Response::err(
                id,
                format!("Storage error: {}", e),
                ErrorCode::STORAGE_ERROR,
            ),
        }
    }
}
