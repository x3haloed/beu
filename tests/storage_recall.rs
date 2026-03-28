use beu::storage::{build_memory_item, Db};
use serde_json::json;

#[tokio::test]
async fn storage_recall_round_trip_prefers_matching_memory_item() {
    let db = Db::open_in_memory().await.unwrap();
    let namespace = "default";
    let payload = json!({
        "claim": "User prefers detailed explanations",
        "support_excerpt": "User asked for a detailed explanation earlier"
    });
    let (item, text) = build_memory_item(
        namespace,
        "invariant",
        "distill",
        "source-1",
        Some("Preference".to_string()),
        Some("User prefers detailed explanations".to_string()),
        Some("inv-1".to_string()),
        payload,
        10,
    );

    db.upsert_memory_item(item, text).await.unwrap();

    let hits = db
        .recall_memory(namespace, "detailed explanation", &[String::from("invariant")], 5)
        .await
        .unwrap();

    assert_eq!(hits.len(), 1);
    assert_eq!(hits[0].source_type, "invariant");
    assert_eq!(hits[0].source_id, "source-1");
    assert!(hits[0].content.contains("detailed"));
}
