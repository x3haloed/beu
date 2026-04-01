use beu::protocol::Protocol;
use beu::storage::Db;
use beu::types::Request;
use serde_json::json;

#[tokio::test]
async fn distill_rejects_model_request_after_loading_thread_history() {
    let db = Db::open_in_memory().await.expect("db");
    let namespace = "distill-thread";

    let index_request = Request {
        version: "1.0.0".to_string(),
        command: "index".to_string(),
        id: "index-1".to_string(),
        namespace: Some(namespace.to_string()),
        payload: json!({
            "entries": [
                {
                    "entry_id": "entry-1",
                    "source_type": "user_turn",
                    "source_id": "session-1",
                    "content": "hello from distill test",
                    "metadata": {
                        "thread_id": "thread-1",
                        "turn_id": "turn-1"
                    }
                }
            ]
        }),
    };
    let index_response = Protocol::handle_request(index_request, &db).await;
    assert!(
        matches!(index_response.status, beu::types::ResponseStatus::Ok { .. }),
        "index should succeed: {:?}",
        index_response
    );

    let distill_request = Request {
        version: "1.0.0".to_string(),
        command: "distill".to_string(),
        id: "distill-1".to_string(),
        namespace: Some(namespace.to_string()),
        payload: json!({
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "provider": "openai_compatible",
            "model": "test-model",
            "base_url": "http://127.0.0.1:9",
            "api_key": "test-key",
            "limit": 4
        }),
    };
    let distill_response = Protocol::handle_request(distill_request, &db).await;
    let error = match distill_response.status {
        beu::types::ResponseStatus::Err { error, .. } => error,
        other => panic!("distill should fail on model request, not succeed: {other:?}"),
    };
    assert!(
        !error.contains("failed to prepare thread history query"),
        "distill should get past thread history query: {error}"
    );
    assert!(
        !error.contains("unsupported distill provider"),
        "distill should accept adapter-normalized provider names: {error}"
    );
}
