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

        CREATE TABLE IF NOT EXISTS memory_items (
            id TEXT PRIMARY KEY,
            namespace_id TEXT NOT NULL,
            item_type TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            title TEXT,
            summary TEXT,
            citation TEXT,
            payload_json TEXT NOT NULL,
            importance INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_memory_items_namespace_type
            ON memory_items(namespace_id, item_type);

        CREATE INDEX IF NOT EXISTS idx_memory_items_namespace_source
            ON memory_items(namespace_id, source_type, source_id);

        CREATE INDEX IF NOT EXISTS idx_memory_items_namespace_updated
            ON memory_items(namespace_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS memory_item_text (
            item_id TEXT PRIMARY KEY,
            namespace_id TEXT NOT NULL,
            content TEXT NOT NULL,
            content_norm TEXT,
            search_hints_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(item_id) REFERENCES memory_items(id)
        );

        CREATE INDEX IF NOT EXISTS idx_memory_item_text_namespace
            ON memory_item_text(namespace_id);

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_item_fts USING fts5(
            item_id UNINDEXED,
            namespace_id UNINDEXED,
            content,
            tokenize = 'porter unicode61'
        );

        CREATE INDEX IF NOT EXISTS idx_events_thread_sequence ON events(thread_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_turns_thread ON turns(thread_id, created_at DESC);
        "#,
    )
    .await?;

    Ok(())
}
