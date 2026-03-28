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
                "SELECT COUNT(*) FROM memory_items WHERE namespace_id = ? AND item_type = ? AND deleted_at IS NULL",
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
            "INSERT INTO memory_items (id, namespace_id, item_type, source_type, source_id, title, summary, citation, payload_json, importance, created_at, updated_at, deleted_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(id) DO UPDATE SET
                namespace_id=excluded.namespace_id,
                item_type=excluded.item_type,
                source_type=excluded.source_type,
                source_id=excluded.source_id,
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
                item.item_type,
                item.source_type,
                item.source_id,
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
            "INSERT INTO memory_item_text (item_id, namespace_id, content, content_norm, search_hints_json, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT(item_id) DO UPDATE SET
                namespace_id=excluded.namespace_id,
                content=excluded.content,
                content_norm=excluded.content_norm,
                search_hints_json=excluded.search_hints_json,
                updated_at=excluded.updated_at",
            libsql::params![
                text.item_id.clone(),
                text.namespace_id.clone(),
                text.content.clone(),
                text.content_norm,
                text.search_hints_json,
                text.created_at,
                text.updated_at,
            ],
        )
        .await?;

        conn.execute(
            "DELETE FROM memory_item_fts WHERE item_id = ?",
            libsql::params![text.item_id.clone()],
        )
        .await?;
        conn.execute(
            "INSERT INTO memory_item_fts (item_id, namespace_id, content) VALUES (?, ?, ?)",
            libsql::params![text.item_id, text.namespace_id, text.content],
        )
        .await?;
        Ok(())
    }

    pub async fn recall_memory(
        &self,
        namespace_id: &str,
        query: &str,
        sources: &[String],
        limit: usize,
    ) -> anyhow::Result<Vec<MemoryRecallHit>> {
        let (_guard, conn) = self.write_connection().await?;
        let normalized_query = normalize_text(query);
        let mut sql = String::from(
            "SELECT m.id, m.item_type AS source_type, m.source_type, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.importance, 0.0 AS rank
             FROM memory_items m
             JOIN memory_item_text t ON t.item_id = m.id
             WHERE m.namespace_id = ? AND m.deleted_at IS NULL",
        );
        let use_fts = !normalized_query.is_empty();
        if use_fts {
            sql = String::from(
                "SELECT m.id, m.item_type AS source_type, m.source_type, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.importance, bm25(memory_item_fts) AS rank
                 FROM memory_item_fts
                 JOIN memory_items m ON m.id = memory_item_fts.item_id
                 JOIN memory_item_text t ON t.item_id = m.id
                 WHERE memory_item_fts MATCH ? AND memory_item_fts.namespace_id = ? AND m.deleted_at IS NULL",
            );
        }
        if !sources.is_empty() {
            sql.push_str(" AND m.item_type IN (SELECT value FROM json_each(?))");
        }
        sql.push_str(" ORDER BY rank ASC, m.importance DESC, m.updated_at DESC LIMIT ?");

        let mut stmt = conn.prepare(&sql).await?;
        let mut rows = if use_fts && sources.is_empty() {
            let fts_query = build_fts_query(&normalized_query);
            stmt.query(libsql::params![fts_query, namespace_id, limit as i64])
                .await?
        } else if use_fts {
            let fts_query = build_fts_query(&normalized_query);
            let source_json = serde_json::to_string(sources)?;
            stmt.query(libsql::params![
                fts_query,
                namespace_id,
                source_json,
                limit as i64
            ])
            .await?
        } else if sources.is_empty() {
            stmt.query(libsql::params![namespace_id, limit as i64])
                .await?
        } else {
            let source_json = serde_json::to_string(sources)?;
            stmt.query(libsql::params![namespace_id, source_json, limit as i64])
                .await?
        };
        let mut hits = Vec::new();
        while let Some(row) = rows.next().await? {
            hits.push(MemoryRecallHit {
                source_type: row.get(1)?,
                source_id: row.get(3)?,
                content: row.get(4)?,
                score: 1.0 / (1.0 + row.get::<f64>(7)?),
                citation: row.get(5)?,
            });
        }
        Ok(hits)
    }
}

#[derive(Debug, Clone)]
pub struct MemoryItemRecord {
    pub id: String,
    pub namespace_id: String,
    pub item_type: String,
    pub source_type: String,
    pub source_id: String,
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
    pub item_id: String,
    pub namespace_id: String,
    pub content: String,
    pub content_norm: Option<String>,
    pub search_hints_json: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone)]
pub struct MemoryRecallHit {
    pub source_type: String,
    pub source_id: String,
    pub content: String,
    pub score: f64,
    pub citation: Option<String>,
}

pub fn build_memory_item(
    namespace_id: &str,
    item_type: &str,
    source_type: &str,
    source_id: &str,
    title: Option<String>,
    summary: Option<String>,
    citation: Option<String>,
    payload: Value,
    importance: i64,
) -> (MemoryItemRecord, MemoryItemTextRecord) {
    let id = Uuid::new_v4().to_string();
    let now = Utc::now().to_rfc3339();
    let payload_json = payload.to_string();
    let content = build_search_document(&title, &summary, &payload);
    let norm = normalize_text(&content);
    let item = MemoryItemRecord {
        id: id.clone(),
        namespace_id: namespace_id.to_string(),
        item_type: item_type.to_string(),
        source_type: source_type.to_string(),
        source_id: source_id.to_string(),
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
        item_id: id,
        namespace_id: namespace_id.to_string(),
        content,
        content_norm: Some(norm),
        search_hints_json: None,
        created_at: now.clone(),
        updated_at: now,
    };
    (item, text)
}

fn build_search_document(
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

fn build_fts_query(normalized_query: &str) -> String {
    let terms = normalized_query
        .split_whitespace()
        .filter(|term| term.len() > 1)
        .map(|term| {
            if term.len() >= 4 {
                format!("{}*", term)
            } else {
                term.to_string()
            }
        })
        .collect::<Vec<_>>();
    if terms.is_empty() {
        normalized_query.to_string()
    } else {
        terms.join(" OR ")
    }
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

fn normalize_text(input: &str) -> String {
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
