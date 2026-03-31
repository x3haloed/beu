use super::*;

impl Protocol {
    pub(super) async fn handle_status(
        id: String,
        namespace: String,
        _payload: Value,
        db: &Db,
    ) -> Response {
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
}
