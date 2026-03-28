use super::Db;

pub async fn run(db: &Db) -> anyhow::Result<()> {
    let conn = db.connect().await?;

    conn.execute_batch(
        r#"
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY,
            root TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS threads (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            external_thread_id TEXT NOT NULL,
            title TEXT NOT NULL,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(agent_id, channel, external_thread_id)
        );
        
        CREATE TABLE IF NOT EXISTS turns (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            status TEXT NOT NULL,
            user_message TEXT NOT NULL,
            assistant_message TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            turn_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        
        -- Memory: Recall chunks with embeddings
        CREATE TABLE IF NOT EXISTS memory_recall_chunks (
            chunk_id TEXT PRIMARY KEY,
            namespace_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            chunk_index INTEGER,
            content TEXT NOT NULL,
            embedding_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        
        -- FTS5 for recall search
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_recall_chunks_fts USING fts5(
            chunk_id,
            namespace_id,
            source_type,
            source_id,
            entry_id,
            content
        );
        
        CREATE INDEX IF NOT EXISTS idx_events_thread_sequence ON events(thread_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_turns_thread ON turns(thread_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_recall_chunks_namespace ON memory_recall_chunks(namespace_id);
        "#,
    )
    .await?;

    Ok(())
}