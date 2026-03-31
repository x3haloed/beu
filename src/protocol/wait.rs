use super::*;

impl Protocol {
    pub(super) async fn handle_wait_hold(
        id: String,
        namespace: String,
        payload: Value,
    ) -> Response {
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
        let token = parsed.token;
        let notify = Arc::new(Notify::new());
        let registry = WAIT_REGISTRY.get_or_init(|| Mutex::new(HashMap::new()));
        {
            let mut guard = registry.lock().expect("wait registry lock");
            guard.insert(token.clone(), notify.clone());
        }
        notify.notified().await;
        Response::ok(
            id,
            serde_json::json!({
                "message": "wait held",
                "token": token,
                "namespace": namespace
            }),
        )
    }

    pub(super) async fn handle_wait_release(
        id: String,
        namespace: String,
        payload: Value,
    ) -> Response {
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
