pub mod ledger;
pub mod migrations;

use chrono::Utc;
use libsql::{Builder, Connection, Database};
use serde_json::Value;
use std::path::Path;
use tokio::sync::Mutex;
use tracing::{debug, error};
use uuid::Uuid;

pub struct Db {
    database: Database,
    write_lock: Mutex<()>,
}

impl Db {
    pub async fn open<P: AsRef<Path>>(path: P) -> anyhow::Result<Self> {
        let path_str = path.as_ref().to_string_lossy().to_string();
        debug!(path = %path_str, "Opening database");
        if let Some(parent) = path.as_ref().parent() {
            tokio::fs::create_dir_all(parent).await?;
        }
        let database = Builder::new_local(&path_str).build().await?;
        let db = Self {
            database,
            write_lock: Mutex::new(()),
        };
        db.initialize().await?;
        debug!("Database initialized successfully");
        Ok(db)
    }

    pub async fn open_in_memory() -> anyhow::Result<Self> {
        let path = std::env::temp_dir().join(format!("beu-memory-{}.sqlite", Uuid::new_v4()));
        debug!(path = %path.display(), "Opening temporary database");
        if let Some(parent) = path.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }
        let database = Builder::new_local(&path).build().await?;
        let db = Self {
            database,
            write_lock: Mutex::new(()),
        };
        db.initialize().await?;
        debug!("Temporary database initialized");
        Ok(db)
    }

    pub async fn open_default() -> anyhow::Result<Self> {
        if let Some(path) = default_db_path() {
            Self::open(path).await
        } else {
            Self::open_in_memory().await
        }
    }

    pub async fn connect(&self) -> anyhow::Result<Connection> {
        let conn = self.database.connect()?;
        Ok(conn)
    }

    pub async fn write_connection(
        &self,
    ) -> anyhow::Result<(tokio::sync::MutexGuard<'_, ()>, Connection)> {
        let guard = self.write_lock.lock().await;
        let conn = self.connect().await?;
        Ok((guard, conn))
    }

    pub async fn initialize(&self) -> anyhow::Result<()> {
        if let Err(e) = migrations::run(self).await {
            error!(error = %e, "Failed to run migrations");
            return Err(e);
        }
        Ok(())
    }

    pub async fn count_memory_items(
        &self,
        namespace_id: &str,
        item_type: &str,
    ) -> anyhow::Result<i64> {
        let conn = self.connect().await?;
        let mut rows = conn
            .query(
                "SELECT COUNT(*) FROM ledger_entries WHERE namespace_id = ? AND entry_type = ? AND deleted_at IS NULL",
                libsql::params![namespace_id, item_type],
            )
            .await?;
        match rows.next().await? {
            Some(row) => Ok(row.get(0)?),
            None => Ok(0),
        }
    }

    pub async fn upsert_memory_item(
        &self,
        item: MemoryItemRecord,
        text: MemoryItemTextRecord,
    ) -> anyhow::Result<()> {
        let (_guard, conn) = self.write_connection().await?;
        conn.execute(
            "INSERT INTO ledger_entries (id, namespace_id, entry_type, source_type, source_id, thread_id, turn_id, title, summary, citation, payload_json, importance, created_at, updated_at, deleted_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(id) DO UPDATE SET
                namespace_id=excluded.namespace_id,
                entry_type=excluded.entry_type,
                source_type=excluded.source_type,
                source_id=excluded.source_id,
                thread_id=excluded.thread_id,
                turn_id=excluded.turn_id,
                title=excluded.title,
                summary=excluded.summary,
                citation=excluded.citation,
                payload_json=excluded.payload_json,
                importance=excluded.importance,
                updated_at=excluded.updated_at,
                deleted_at=excluded.deleted_at",
            libsql::params![
                item.id,
                item.namespace_id,
                item.entry_type,
                item.source_type,
                item.source_id,
                item.thread_id,
                item.turn_id,
                item.title,
                item.summary,
                item.citation,
                item.payload_json,
                item.importance,
                item.created_at,
                item.updated_at,
                item.deleted_at,
            ],
        )
        .await?;

        conn.execute(
            "INSERT INTO ledger_entry_chunks (chunk_id, namespace_id, entry_id, chunk_index, content, content_norm, search_hints_json, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(chunk_id) DO UPDATE SET
                namespace_id=excluded.namespace_id,
                entry_id=excluded.entry_id,
                chunk_index=excluded.chunk_index,
                content=excluded.content,
                content_norm=excluded.content_norm,
                search_hints_json=excluded.search_hints_json,
                updated_at=excluded.updated_at",
            libsql::params![
                text.chunk_id.clone(),
                text.namespace_id.clone(),
                text.entry_id.clone(),
                text.chunk_index,
                text.content.clone(),
                text.content_norm,
                text.search_hints_json,
                text.created_at.clone(),
                text.updated_at.clone(),
            ],
        )
        .await?;

        conn.execute(
            "DELETE FROM ledger_entry_chunks_fts WHERE chunk_id = ?",
            libsql::params![text.chunk_id.clone()],
        )
        .await?;
        conn.execute(
            "INSERT INTO ledger_entry_chunks_fts (chunk_id, namespace_id, content) VALUES (?, ?, ?)",
            libsql::params![text.chunk_id.clone(), text.namespace_id.clone(), text.content.clone()],
        )
        .await?;
        if let Some(embedding_json) = text.embedding_json.clone() {
            conn.execute(
                "INSERT INTO ledger_entry_embeddings (chunk_id, namespace_id, embedding, embedding_model, embedding_provider, embedding_dims, created_at, updated_at)
                 VALUES (?, ?, vector(?), ?, ?, ?, ?, ?)
                 ON CONFLICT(chunk_id) DO UPDATE SET
                    namespace_id=excluded.namespace_id,
                    embedding=excluded.embedding,
                    embedding_model=excluded.embedding_model,
                    embedding_provider=excluded.embedding_provider,
                    embedding_dims=excluded.embedding_dims,
                    updated_at=excluded.updated_at",
                libsql::params![
                    text.chunk_id.clone(),
                    text.namespace_id.clone(),
                    embedding_json,
                    text.embedding_model,
                    text.embedding_provider,
                    text.embedding_dims,
                    text.created_at.clone(),
                    text.updated_at.clone(),
                ],
            )
            .await?;
        }
        Ok(())
    }

pub async fn recall_memory(
        &self,
        namespace_id: &str,
        query: &str,
        limit: usize,
    ) -> anyhow::Result<Vec<MemoryRecallHit>> {
        let (_guard, conn) = self.write_connection().await?;
        let normalized_query = normalize_text(query);
        let query_terms = tokenize_terms(&normalized_query);
        let expanded_terms = expand_query_terms(&query_terms);
        let fts_query = build_fts_query(&expanded_terms);

        let mut sql = String::from(
            "SELECT m.id, m.entry_type AS source_type, m.source_type, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.importance, m.updated_at, 0.0 AS rank
             FROM ledger_entries m
             JOIN ledger_entry_chunks t ON t.entry_id = m.id
             WHERE m.namespace_id = ? AND m.deleted_at IS NULL AND m.entry_type IN ('user_turn', 'assistant_turn', 'tool_result')",
        );
        let use_fts = !fts_query.is_empty();
        if use_fts {
            sql = String::from(
                "SELECT m.id, m.entry_type AS source_type, m.source_type, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.importance, m.updated_at, bm25(ledger_entry_chunks_fts) AS rank
                 FROM ledger_entry_chunks_fts
                 JOIN ledger_entry_chunks t ON t.chunk_id = ledger_entry_chunks_fts.chunk_id
                 JOIN ledger_entries m ON m.id = t.entry_id
                 WHERE ledger_entry_chunks_fts MATCH ? AND ledger_entry_chunks_fts.namespace_id = ? AND m.deleted_at IS NULL AND m.entry_type IN ('user_turn', 'assistant_turn', 'tool_result')",
            );
        }
        sql.push_str(" ORDER BY rank ASC, m.importance DESC, m.updated_at DESC LIMIT ?");

        let mut stmt = conn.prepare(&sql).await?;
        let candidate_limit = (limit.saturating_mul(5)).max(20) as i64;
        let mut rows = if use_fts {
            stmt.query(libsql::params![fts_query, namespace_id, candidate_limit])
                .await?
        } else {
            stmt.query(libsql::params![namespace_id, candidate_limit])
                .await?
        };
        let mut candidates = Vec::new();
        while let Some(row) = rows.next().await? {
            candidates.push(RecallCandidate {
                source_type: row.get(1)?,
                source_id: row.get(3)?,
                content: row.get(4)?,
                citation: row.get(5)?,
                importance: row.get(6)?,
                updated_at: row.get(7)?,
                bm25_rank: row.get(8)?,
            });
        }
        Ok(rerank_candidates(candidates, &query_terms, query, limit))
    }
}

#[derive(Debug, Clone)]
pub struct MemoryItemRecord {
    pub id: String,
    pub namespace_id: String,
    pub entry_type: String,
    pub source_type: String,
    pub source_id: String,
    pub thread_id: Option<String>,
    pub turn_id: Option<String>,
    pub title: Option<String>,
    pub summary: Option<String>,
    pub citation: Option<String>,
    pub payload_json: String,
    pub importance: i64,
    pub created_at: String,
    pub updated_at: String,
    pub deleted_at: Option<String>,
}

#[derive(Debug, Clone)]
pub struct MemoryItemTextRecord {
    pub chunk_id: String,
    pub namespace_id: String,
    pub entry_id: String,
    pub chunk_index: i64,
    pub content: String,
    pub content_norm: Option<String>,
    pub search_hints_json: Option<String>,
    pub created_at: String,
    pub updated_at: String,
    pub embedding_json: Option<String>,
    pub embedding_model: Option<String>,
    pub embedding_provider: Option<String>,
    pub embedding_dims: i64,
}

#[derive(Debug, Clone)]
pub struct MemoryRecallHit {
    pub source_type: String,
    pub source_id: String,
    pub content: String,
    pub score: f64,
    pub citation: Option<String>,
}

#[derive(Debug, Clone)]
struct RecallCandidate {
    source_type: String,
    source_id: String,
    content: String,
    citation: Option<String>,
    importance: i64,
    updated_at: String,
    bm25_rank: f64,
}

pub fn build_memory_item(
    namespace_id: &str,
    entry_type: &str,
    source_type: &str,
    source_id: &str,
    title: Option<String>,
    summary: Option<String>,
    citation: Option<String>,
    payload: Value,
    importance: i64,
    embedding: Option<Vec<f32>>,
) -> (MemoryItemRecord, MemoryItemTextRecord) {
    let id = Uuid::new_v4().to_string();
    let now = Utc::now().to_rfc3339();
    let payload_json = payload.to_string();
    let content = build_search_document(&title, &summary, &payload);
    let norm = normalize_text(&content);
    let thread_id = payload
        .get("metadata")
        .and_then(|m| m.get("thread_id"))
        .and_then(Value::as_str)
        .map(|s| s.to_string());
    let turn_id = payload
        .get("metadata")
        .and_then(|m| m.get("turn_id"))
        .and_then(Value::as_str)
        .map(|s| s.to_string());
    let chunk_id = Uuid::new_v4().to_string();
    let embedding_json = embedding.as_ref().map(|vec| serde_json::to_string(vec).unwrap());
    let item = MemoryItemRecord {
        id: id.clone(),
        namespace_id: namespace_id.to_string(),
        entry_type: entry_type.to_string(),
        source_type: source_type.to_string(),
        source_id: source_id.to_string(),
        thread_id,
        turn_id,
        title,
        summary,
        citation,
        payload_json,
        importance,
        created_at: now.clone(),
        updated_at: now.clone(),
        deleted_at: None,
    };
    let text = MemoryItemTextRecord {
        chunk_id,
        namespace_id: namespace_id.to_string(),
        entry_id: id,
        chunk_index: 0,
        content,
        content_norm: Some(norm),
        search_hints_json: None,
        created_at: now.clone(),
        updated_at: now,
        embedding_json,
        embedding_model: None,
        embedding_provider: None,
        embedding_dims: embedding.as_ref().map(|v| v.len() as i64).unwrap_or(1536),
    };
    (item, text)
}

pub(crate) fn build_search_document(
    title: &Option<String>,
    summary: &Option<String>,
    payload: &Value,
) -> String {
    let mut parts = Vec::new();
    if let Some(title) = title.as_ref().filter(|s| !s.trim().is_empty()) {
        parts.push(title.clone());
    }
    if let Some(summary) = summary.as_ref().filter(|s| !s.trim().is_empty()) {
        parts.push(summary.clone());
    }
    if let Some(claim) = payload.get("claim").and_then(Value::as_str) {
        parts.push(claim.to_string());
    }
    if let Some(support) = payload.get("support_excerpt").and_then(Value::as_str) {
        parts.push(support.to_string());
    }
    if let Some(falsifier) = payload.get("falsifier").and_then(Value::as_str) {
        parts.push(falsifier.to_string());
    }
    if let Some(content) = payload.get("content").and_then(Value::as_str) {
        parts.push(content.to_string());
    }
    parts.join("\n")
}

pub(crate) fn build_fts_query(terms: &[String]) -> String {
    let terms = terms
        .iter()
        .filter(|term| term.len() > 1)
        .map(|term| {
            if term.len() >= 4 {
                format!("{}*", term)
            } else {
                term.clone()
            }
        })
        .collect::<Vec<_>>();
    if terms.is_empty() {
        String::new()
    } else {
        terms.join(" OR ")
    }
}

pub(crate) fn tokenize_terms(normalized_query: &str) -> Vec<String> {
    normalized_query
        .split_whitespace()
        .filter(|term| !term.is_empty())
        .map(|term| term.to_string())
        .collect()
}

pub(crate) fn expand_query_terms(terms: &[String]) -> Vec<String> {
    let mut expanded = Vec::new();
    for term in terms {
        push_unique(&mut expanded, term.clone());
        for synonym in query_synonyms(term) {
            push_unique(&mut expanded, synonym.to_string());
        }
    }
    expanded
}

fn query_synonyms(term: &str) -> &'static [&'static str] {
    match term {
        "detailed" | "detail" | "details" | "verbose" | "wordy" | "lengthy" => {
            &["detailed", "verbose", "long", "expanded"]
        }
        "explain" | "explains" | "explained" | "explanation" | "why" => {
            &["explanation", "reason", "because", "why"]
        }
        "preference" | "prefer" | "prefers" | "preferred" => {
            &["prefer", "prefers", "preference", "likes"]
        }
        "remember" | "recall" | "memory" => &["remember", "recall", "memory", "recollect"],
        "short" | "brief" | "concise" => &["short", "brief", "concise", "succinct"],
        _ => &[],
    }
}

fn push_unique(values: &mut Vec<String>, candidate: String) {
    if !values.iter().any(|existing| existing == &candidate) {
        values.push(candidate);
    }
}

fn rerank_candidates(
    mut candidates: Vec<RecallCandidate>,
    query_terms: &[String],
    query: &str,
    limit: usize,
) -> Vec<MemoryRecallHit> {
    let query_phrase = normalize_text(query);
    for candidate in &mut candidates {
        candidate.bm25_rank = score_candidate(candidate, query_terms, &query_phrase);
    }
    candidates.sort_by(|a, b| {
        b.bm25_rank
            .partial_cmp(&a.bm25_rank)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| b.importance.cmp(&a.importance))
            .then_with(|| b.updated_at.cmp(&a.updated_at))
    });
    candidates
        .into_iter()
        .take(limit)
        .map(|candidate| MemoryRecallHit {
            source_type: candidate.source_type,
            source_id: candidate.source_id,
            content: candidate.content,
            score: candidate.bm25_rank,
            citation: candidate.citation,
        })
        .collect()
}

fn score_candidate(candidate: &RecallCandidate, query_terms: &[String], query_phrase: &str) -> f64 {
    let haystack = normalize_text(&candidate.content);
    let mut score = 0.0;
    if !query_phrase.is_empty() && haystack.contains(query_phrase) {
        score += 6.0;
    }
    for term in query_terms {
        if term.len() < 2 {
            continue;
        }
        if haystack.contains(term) {
            score += 2.0;
        } else if has_prefix_match(&haystack, term) {
            score += 1.25;
        }
        for synonym in query_synonyms(term) {
            if haystack.contains(synonym) {
                score += 1.5;
            }
        }
    }
    score += candidate.importance as f64 * 0.2;
    score += candidate.bm25_rank.abs() * 0.1;
    score
}

fn has_prefix_match(haystack: &str, term: &str) -> bool {
    haystack
        .split_whitespace()
        .any(|candidate| candidate.starts_with(term) || term.starts_with(candidate))
}

pub async fn create_db<P: AsRef<Path>>(path: P) -> anyhow::Result<Db> {
    Db::open(path).await
}

pub fn default_db_path() -> Option<std::path::PathBuf> {
    use directories::ProjectDirs;

    if let Ok(path) = std::env::var("BEU_DB_PATH") {
        let trimmed = path.trim();
        if !trimmed.is_empty() {
            return Some(std::path::PathBuf::from(trimmed));
        }
    }

    if let Ok(root) = std::env::var("BEU_STATE_DIR") {
        let trimmed = root.trim();
        if !trimmed.is_empty() {
            return Some(
                std::path::PathBuf::from(trimmed)
                    .join("memory")
                    .join("beu.sqlite"),
            );
        }
    }

    if let Ok(home) = std::env::var("HERMES_HOME") {
        let trimmed = home.trim();
        if !trimmed.is_empty() {
            return Some(
                std::path::PathBuf::from(trimmed)
                    .join("memory")
                    .join("beu.sqlite"),
            );
        }
    }

    if let Ok(state_dir) = std::env::var("OPENCLAW_STATE_DIR") {
        let trimmed = state_dir.trim();
        if !trimmed.is_empty() {
            return Some(
                std::path::PathBuf::from(trimmed)
                    .join("memory")
                    .join("beu.sqlite"),
            );
        }
    }

    ProjectDirs::from("dev", "beu", "beu")
        .map(|dirs| dirs.data_local_dir().join("memory").join("beu.sqlite"))
}

pub(crate) fn normalize_text(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    let mut last_space = false;
    for ch in input.chars().flat_map(|c| c.to_lowercase()) {
        if ch.is_ascii_alphanumeric() {
            out.push(ch);
            last_space = false;
        } else if !last_space {
            out.push(' ');
            last_space = true;
        }
    }
    out.split_whitespace().collect::<Vec<_>>().join(" ")
}
