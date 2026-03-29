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

        CREATE TABLE IF NOT EXISTS ledger_entries (
            id TEXT PRIMARY KEY,
            namespace_id TEXT NOT NULL,
            entry_type TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            thread_id TEXT,
            turn_id TEXT,
            title TEXT,
            summary TEXT,
            citation TEXT,
            payload_json TEXT NOT NULL,
            importance INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_ledger_entries_namespace_type
            ON ledger_entries(namespace_id, entry_type);

        CREATE INDEX IF NOT EXISTS idx_ledger_entries_namespace_source
            ON ledger_entries(namespace_id, source_type, source_id);

        CREATE INDEX IF NOT EXISTS idx_ledger_entries_namespace_updated
            ON ledger_entries(namespace_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS ledger_entry_chunks (
            chunk_id TEXT PRIMARY KEY,
            namespace_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            content TEXT NOT NULL,
            content_norm TEXT,
            search_hints_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES ledger_entries(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ledger_entry_chunks_namespace
            ON ledger_entry_chunks(namespace_id, entry_id, chunk_index);

        CREATE VIRTUAL TABLE IF NOT EXISTS ledger_entry_chunks_fts USING fts5(
            chunk_id UNINDEXED,
            namespace_id UNINDEXED,
            content,
            tokenize = 'porter unicode61'
        );

        CREATE TABLE IF NOT EXISTS ledger_entry_embeddings (
            chunk_id TEXT PRIMARY KEY,
            namespace_id TEXT NOT NULL,
            embedding F32_BLOB(768) NOT NULL,
            embedding_model TEXT,
            embedding_provider TEXT,
            embedding_dims INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(chunk_id) REFERENCES ledger_entry_chunks(chunk_id)
        );

        CREATE INDEX IF NOT EXISTS idx_ledger_entry_embeddings_namespace
            ON ledger_entry_embeddings(namespace_id);

        CREATE INDEX IF NOT EXISTS idx_ledger_entry_embeddings_vector
            ON ledger_entry_embeddings(libsql_vector_idx(embedding));

        CREATE INDEX IF NOT EXISTS idx_events_thread_sequence ON events(thread_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_turns_thread ON turns(thread_id, created_at DESC);
        "#,
    )
    .await?;

    Ok(())
}
