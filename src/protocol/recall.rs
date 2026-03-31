use super::*;

impl Protocol {
    pub(super) async fn handle_recall(
        id: String,
        namespace: String,
        payload: Value,
        db: &Db,
    ) -> Response {
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
        match db.recall_memory(&ns, &parsed.query, parsed.limit).await {
            Ok(hits) => {
                let hits_json = hits
                    .into_iter()
                    .map(|hit| {
                        serde_json::json!({
                            "entry_id": hit.entry_id,
                            "source_type": hit.source_type,
                            "source_id": hit.source_id,
                            "content": hit.content,
                            "score": hit.score,
                            "citation": hit.citation,
                        })
                    })
                    .collect::<Vec<_>>();
                let ledger_recall_block = build_ledger_recall_block(&ns, &hits_json);
                Response::ok(
                    id,
                    serde_json::json!({
                        "hits": hits_json,
                        "ledger_recall_block": ledger_recall_block,
                    }),
                )
            }
            Err(e) => Response::err(
                id,
                format!("Storage error: {}", e),
                ErrorCode::STORAGE_ERROR,
            ),
        }
    }
}
