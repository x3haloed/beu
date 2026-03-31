use super::*;

impl Protocol {
    pub(super) async fn handle_index(
        id: String,
        namespace: String,
        payload: Value,
        db: &Db,
    ) -> Response {
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
}
