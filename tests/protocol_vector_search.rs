use beu::protocol::Protocol;
use beu::storage::{build_memory_item, Db};
use beu::types::{Request, ResponseStatus};
use serde_json::Value;

fn load_embedding(fixture: &str) -> Vec<f32> {
    let json: Value = serde_json::from_str(fixture).expect("embedding fixture json");
    serde_json::from_value(json["data"][0]["embedding"].clone()).expect("embedding vector")
}

fn query_embedding() -> Vec<f32> {
    load_embedding(include_str!("fixtures/query_embedding.json"))
}

fn distractor_embedding() -> Vec<f32> {
    load_embedding(include_str!("fixtures/distractor_embedding.json"))
}

#[tokio::test]
async fn protocol_ledger_search_uses_native_vector_similarity() {
    let db = Db::open_in_memory().await.unwrap();
    let namespace = "vector-test";
    let target_embedding = query_embedding();
    let distractor_embedding = distractor_embedding();

    assert_eq!(target_embedding.len(), 768);
    assert_eq!(distractor_embedding.len(), 768);

    let (target_item, target_text) = build_memory_item(
        namespace,
        "user_turn",
        "turn-target",
        "turn-target",
        Some("User message".to_string()),
        Some("User prefers verbose technical explanations and detailed answers".to_string()),
        Some("turn-target".to_string()),
        serde_json::json!({
            "claim": "User prefers verbose technical explanations and detailed answers",
            "support_excerpt": "The user repeatedly asked for detailed, technical, and verbose explanations"
        }),
        10,
        Some(target_embedding),
    );
    let (distractor_item, distractor_text) = build_memory_item(
        namespace,
        "assistant_turn",
        "turn-distractor",
        "turn-distractor",
        Some("Assistant message".to_string()),
        Some("A recipe for pasta with tomatoes and basil".to_string()),
        Some("turn-distractor".to_string()),
        serde_json::json!({
            "claim": "A recipe for pasta with tomatoes and basil",
            "support_excerpt": "Dinner idea with olive oil and parmesan"
        }),
        10,
        Some(distractor_embedding),
    );

    db.upsert_memory_item(target_item, target_text).await.unwrap();
    db.upsert_memory_item(distractor_item, distractor_text).await.unwrap();

    let request = Request {
        version: "1.0.0".to_string(),
        command: "ledger_search".to_string(),
        id: "search-vector-1".to_string(),
        namespace: Some(namespace.to_string()),
        payload: serde_json::json!({
            "query": "User prefers verbose technical explanations and detailed answers",
            "query_embedding": query_embedding(),
            "limit": 5
        }),
    };

    let response = Protocol::handle_request(request, &db).await;
    let data = match response.status {
        ResponseStatus::Ok { data, .. } => data,
        other => panic!("expected ok response, got {other:?}"),
    };
    let entries = data["entries"].as_array().unwrap();
    assert!(!entries.is_empty());
    assert_eq!(entries[0]["source_id"], "turn-target");
}
