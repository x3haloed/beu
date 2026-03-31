use super::*;

impl Protocol {
    pub(super) async fn handle_ledger_list(
        id: String,
        namespace: String,
        payload: Value,
        db: &Db,
    ) -> Response {
        let parsed: LedgerListPayload = match serde_json::from_value(payload.clone()) {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Invalid ledger_list payload: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
            }
        };
        let ns = parsed.namespace.unwrap_or(namespace);
        let (_guard, conn) = match db.write_connection().await {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Storage error: {}", e),
                    ErrorCode::STORAGE_ERROR,
                )
            }
        };
        let mut sql = String::from(
            "SELECT m.id, m.entry_type, m.thread_id, m.turn_id, m.source_type, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.updated_at
             FROM ledger_entries m
             JOIN ledger_entry_chunks t ON t.entry_id = m.id
             WHERE m.namespace_id = ? AND m.deleted_at IS NULL AND m.entry_type IN ('user_turn', 'assistant_turn', 'tool_result')",
        );
        if parsed.thread_id.is_some() {
            sql.push_str(" AND m.thread_id = ?");
        }
        sql.push_str(" ORDER BY m.updated_at DESC LIMIT ?");
        let mut stmt = match conn.prepare(&sql).await {
            Ok(stmt) => stmt,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Storage error: {}", e),
                    ErrorCode::STORAGE_ERROR,
                )
            }
        };
        let ns_param = ns.clone();
        let rows = match parsed.thread_id.as_ref() {
            Some(thread_id) => {
                stmt.query(libsql::params![
                    ns_param.clone(),
                    thread_id.clone(),
                    parsed.limit as i64
                ])
                .await
            }
            None => {
                stmt.query(libsql::params![ns_param.clone(), parsed.limit as i64])
                    .await
            }
        };
        let mut rows = match rows {
            Ok(rows) => rows,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Storage error: {}", e),
                    ErrorCode::STORAGE_ERROR,
                )
            }
        };
        let mut entries = Vec::new();
        while let Some(row) = match rows.next().await {
            Ok(row) => row,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Storage error: {}", e),
                    ErrorCode::STORAGE_ERROR,
                )
            }
        } {
            entries.push(serde_json::json!({
                "entry_id": row.get::<String>(0).unwrap_or_default(),
                "thread_id": row.get::<Option<String>>(2).unwrap_or(None),
                "turn_id": row.get::<Option<String>>(3).unwrap_or(None),
                "created_at": row.get::<String>(8).unwrap_or_default(),
                "citation": row.get::<Option<String>>(7).unwrap_or(None),
                "summary": row.get::<String>(6).unwrap_or_default(),
            }));
        }
        Response::ok(
            id,
            serde_json::json!({
                "entries": entries,
                "entry_count": entries.len(),
                "truncated": false,
                "limit_reached": serde_json::Value::Null,
                "namespace": ns
            }),
        )
    }

    pub(super) async fn handle_ledger_search(
        id: String,
        namespace: String,
        payload: Value,
        db: &Db,
    ) -> Response {
        let parsed: LedgerSearchPayload = match serde_json::from_value(payload.clone()) {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Invalid ledger_search payload: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
            }
        };
        let ns = parsed.namespace.unwrap_or(namespace);
        let (_guard, conn) = match db.write_connection().await {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Storage error: {}", e),
                    ErrorCode::STORAGE_ERROR,
                )
            }
        };
        let limit = parsed.limit as i64;
        let query_embedding = parsed
            .query_embedding
            .as_ref()
            .map(|vec| serde_json::to_string(vec).unwrap());
        let mut entries = Vec::new();

        if let Some(query_embedding) = query_embedding {
            let mut sql = String::from(
                "SELECT m.id, m.entry_type, m.thread_id, m.turn_id, m.source_type, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.updated_at, vector_distance_cos(e.embedding, vector(?)) AS rank
                 FROM ledger_entry_embeddings e
                 JOIN ledger_entry_chunks t ON t.chunk_id = e.chunk_id
                 JOIN ledger_entries m ON m.id = t.entry_id
                 WHERE e.namespace_id = ? AND m.namespace_id = ? AND m.deleted_at IS NULL AND m.entry_type IN ('user_turn', 'assistant_turn', 'tool_result')",
            );
            if parsed.thread_id.is_some() {
                sql.push_str(" AND m.thread_id = ?");
            }
            sql.push_str(" ORDER BY rank ASC, m.updated_at DESC LIMIT ?");
            let mut stmt = match conn.prepare(&sql).await {
                Ok(stmt) => stmt,
                Err(e) => {
                    return Response::err(
                        id,
                        format!("Storage error: {}", e),
                        ErrorCode::STORAGE_ERROR,
                    )
                }
            };
            let rows = match parsed.thread_id.as_ref() {
                Some(thread_id) => {
                    stmt.query(libsql::params![
                        query_embedding,
                        ns.clone(),
                        ns.clone(),
                        thread_id.clone(),
                        limit
                    ])
                    .await
                }
                None => {
                    stmt.query(libsql::params![
                        query_embedding,
                        ns.clone(),
                        ns.clone(),
                        limit
                    ])
                    .await
                }
            };
            let mut rows: libsql::Rows = match rows {
                Ok(rows) => rows,
                Err(e) => {
                    return Response::err(
                        id,
                        format!("Storage error: {}", e),
                        ErrorCode::STORAGE_ERROR,
                    )
                }
            };
            while let Some(row) = match rows.next().await {
                Ok(row) => row,
                Err(e) => {
                    return Response::err(
                        id,
                        format!("Storage error: {}", e),
                        ErrorCode::STORAGE_ERROR,
                    )
                }
            } {
                entries.push(serde_json::json!({
                    "entry_id": row.get::<String>(0).unwrap_or_default(),
                    "thread_id": row.get::<Option<String>>(2).unwrap_or(None),
                    "turn_id": row.get::<Option<String>>(3).unwrap_or(None),
                    "source_type": row.get::<String>(4).unwrap_or_default(),
                    "source_id": row.get::<String>(5).unwrap_or_default(),
                    "created_at": row.get::<String>(8).unwrap_or_default(),
                    "citation": row.get::<Option<String>>(7).unwrap_or(None),
                    "summary": row.get::<String>(6).unwrap_or_default(),
                    "content": row.get::<String>(6).unwrap_or_default(),
                    "score": row.get::<f64>(9).unwrap_or_default(),
                    "matched_chunk": row.get::<String>(6).unwrap_or_default(),
                }));
            }
        } else {
            let normalized_query = normalize_text(&parsed.query);
            let query_terms = tokenize_terms(&normalized_query);
            let expanded_terms = expand_query_terms(&query_terms);
            let fts_query = build_fts_query(&expanded_terms);
            let mut sql = String::from(
                "SELECT m.id, m.entry_type, m.thread_id, m.turn_id, m.source_type, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.updated_at, bm25(ledger_entry_chunks_fts) AS rank
                 FROM ledger_entry_chunks_fts
                 JOIN ledger_entry_chunks t ON t.chunk_id = ledger_entry_chunks_fts.chunk_id
                 JOIN ledger_entries m ON m.id = t.entry_id
                 WHERE ledger_entry_chunks_fts MATCH ? AND ledger_entry_chunks_fts.namespace_id = ? AND m.deleted_at IS NULL AND m.entry_type IN ('user_turn', 'assistant_turn', 'tool_result')",
            );
            if parsed.thread_id.is_some() {
                sql.push_str(" AND m.thread_id = ?");
            }
            sql.push_str(" ORDER BY rank ASC, m.updated_at DESC LIMIT ?");
            let mut stmt = match conn.prepare(&sql).await {
                Ok(stmt) => stmt,
                Err(e) => {
                    return Response::err(
                        id,
                        format!("Storage error: {}", e),
                        ErrorCode::STORAGE_ERROR,
                    )
                }
            };
            let rows = match parsed.thread_id.as_ref() {
                Some(thread_id) => {
                    stmt.query(libsql::params![
                        fts_query,
                        ns.clone(),
                        thread_id.clone(),
                        limit
                    ])
                    .await
                }
                None => {
                    stmt.query(libsql::params![fts_query, ns.clone(), limit])
                        .await
                }
            };
            let mut rows: libsql::Rows = match rows {
                Ok(rows) => rows,
                Err(e) => {
                    return Response::err(
                        id,
                        format!("Storage error: {}", e),
                        ErrorCode::STORAGE_ERROR,
                    )
                }
            };
            while let Some(row) = match rows.next().await {
                Ok(row) => row,
                Err(e) => {
                    return Response::err(
                        id,
                        format!("Storage error: {}", e),
                        ErrorCode::STORAGE_ERROR,
                    )
                }
            } {
                entries.push(serde_json::json!({
                    "entry_id": row.get::<String>(0).unwrap_or_default(),
                    "thread_id": row.get::<Option<String>>(2).unwrap_or(None),
                    "turn_id": row.get::<Option<String>>(3).unwrap_or(None),
                    "source_type": row.get::<String>(4).unwrap_or_default(),
                    "source_id": row.get::<String>(5).unwrap_or_default(),
                    "created_at": row.get::<String>(8).unwrap_or_default(),
                    "citation": row.get::<Option<String>>(7).unwrap_or(None),
                    "summary": row.get::<String>(6).unwrap_or_default(),
                    "content": row.get::<String>(6).unwrap_or_default(),
                    "score": row.get::<f64>(9).unwrap_or_default(),
                    "matched_chunk": row.get::<String>(6).unwrap_or_default(),
                }));
            }
        }
        Response::ok(
            id,
            serde_json::json!({
                "query": parsed.query,
                "entries": entries,
                "entry_count": entries.len(),
                "namespace": ns
            }),
        )
    }

    pub(super) async fn handle_ledger_get(
        id: String,
        namespace: String,
        payload: Value,
        db: &Db,
    ) -> Response {
        let parsed: LedgerGetPayload = match serde_json::from_value(payload.clone()) {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Invalid ledger_get payload: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
            }
        };
        let ns = parsed.namespace.unwrap_or(namespace);
        let entry_id = parsed.entry_id.clone();
        let (_guard, conn) = match db.write_connection().await {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Storage error: {}", e),
                    ErrorCode::STORAGE_ERROR,
                )
            }
        };
        let mut stmt = match conn
            .prepare(
                "SELECT m.id, m.entry_type, m.thread_id, m.turn_id, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.payload_json, m.updated_at
                 FROM ledger_entries m
                 JOIN ledger_entry_chunks t ON t.entry_id = m.id
                 WHERE m.namespace_id = ? AND m.id = ? AND m.deleted_at IS NULL
                 LIMIT 1",
            )
            .await
        {
            Ok(stmt) => stmt,
            Err(e) => return Response::err(id, format!("Storage error: {}", e), ErrorCode::STORAGE_ERROR),
        };
        let mut rows: libsql::Rows = match stmt
            .query(libsql::params![ns.clone(), entry_id.clone()])
            .await
        {
            Ok(rows) => rows,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Storage error: {}", e),
                    ErrorCode::STORAGE_ERROR,
                )
            }
        };
        match rows.next().await {
            Ok(Some(row)) => Response::ok(
                id,
                serde_json::json!({
                    "entry_id": row.get::<String>(0).unwrap_or_default(),
                    "thread_id": row.get::<Option<String>>(2).unwrap_or(None),
                    "turn_id": row.get::<Option<String>>(3).unwrap_or(None),
                    "created_at": row.get::<String>(8).unwrap_or_default(),
                    "citation": row.get::<Option<String>>(6).unwrap_or(None),
                    "content": row.get::<String>(5).unwrap_or_default(),
                    "payload": row.get::<String>(7).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()),
                }),
            ),
            Ok(None) => Response::err(
                id,
                format!("ledger entry not found: {}", entry_id),
                ErrorCode::NOT_FOUND,
            ),
            Err(e) => Response::err(
                id,
                format!("Storage error: {}", e),
                ErrorCode::STORAGE_ERROR,
            ),
        }
    }
}
