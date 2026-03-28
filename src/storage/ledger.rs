use super::Db;
use crate::types::ledger::Event;
use chrono::Utc;
use libsql::params;
use uuid::Uuid;

pub struct Ledger {
    db: Db,
}

impl Ledger {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    pub async fn create_thread(
        &self,
        agent_id: &str,
        channel: &str,
        external_thread_id: &str,
    ) -> anyhow::Result<String> {
        let (_guard, conn) = self.db.write_connection().await?;
        let thread_id = Uuid::new_v4().to_string();
        let now = Utc::now().to_rfc3339();

        conn.execute(
            "INSERT INTO threads (id, agent_id, channel, external_thread_id, title, metadata_json, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            params![
                thread_id.clone(),
                agent_id.to_string(),
                channel.to_string(),
                external_thread_id.to_string(),
                "".to_string(),
                "null".to_string(),
                now.clone(),
                now
            ],
        )
        .await?;

        Ok(thread_id)
    }

    pub async fn create_turn(&self, thread_id: &str, user_message: &str) -> anyhow::Result<String> {
        let (_guard, conn) = self.db.write_connection().await?;
        let turn_id = Uuid::new_v4().to_string();
        let now = Utc::now().to_rfc3339();

        conn.execute(
            "INSERT INTO turns (id, thread_id, status, user_message, assistant_message, error, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            params![
                turn_id.clone(),
                thread_id.to_string(),
                "pending".to_string(),
                user_message.to_string(),
                "".to_string(),
                "".to_string(),
                now.clone(),
                now
            ],
        )
        .await?;

        Ok(turn_id)
    }

    pub async fn append_event(
        &self,
        turn_id: &str,
        thread_id: &str,
        kind: &str,
        payload: &str,
    ) -> anyhow::Result<String> {
        let (_guard, conn) = self.db.write_connection().await?;
        let event_id = Uuid::new_v4().to_string();
        let now = Utc::now().to_rfc3339();

        let mut rows: libsql::Rows = conn
            .query(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE turn_id = ?",
                params![turn_id.to_string()],
            )
            .await?;
        let sequence: i64 = match rows.next().await? {
            Some(row) => row.get(0)?,
            None => 1,
        };

        conn.execute(
            "INSERT INTO events (id, turn_id, thread_id, sequence, kind, payload, created_at)
             VALUES (?, ?, ?, ?, ?, ?, ?)",
            params![
                event_id.clone(),
                turn_id.to_string(),
                thread_id.to_string(),
                sequence,
                kind.to_string(),
                payload.to_string(),
                now
            ],
        )
        .await?;

        Ok(event_id)
    }

    pub async fn get_thread_events(&self, thread_id: &str) -> anyhow::Result<Vec<Event>> {
        let (_guard, conn) = self.db.write_connection().await?;
        let mut stmt: libsql::Statement = conn
            .prepare(
                "SELECT id, turn_id, thread_id, sequence, kind, payload, created_at 
             FROM events WHERE thread_id = ? ORDER BY sequence",
            )
            .await?;

        let mut rows: libsql::Rows = stmt.query(params![thread_id.to_string()]).await?;
        let mut events = Vec::new();

        while let Some(row) = rows.next().await? {
            events.push(Event {
                id: row.get(0)?,
                turn_id: row.get(1)?,
                thread_id: row.get(2)?,
                sequence: row.get(3)?,
                kind: row.get(4)?,
                payload: row.get(5)?,
                created_at: row.get(6)?,
            });
        }

        Ok(events)
    }
}

#[cfg(test)]
mod tests {
    use super::Ledger;
    use crate::storage::Db;
    use tempfile::TempDir;

    #[tokio::test]
    async fn test_ledger_operations() {
        let tmp_dir = TempDir::new().unwrap();
        let db_path = tmp_dir.path().join("test.db");
        let db = Db::open(&db_path).await.unwrap();

        let ledger = Ledger::new(db);

        // Create thread
        let thread_id = ledger
            .create_thread("test-agent", "cli", "test-session")
            .await
            .unwrap();
        assert!(!thread_id.is_empty());

        // Create turn
        let turn_id = ledger.create_turn(&thread_id, "Hello world").await.unwrap();
        assert!(!turn_id.is_empty());

        // Append event
        let event_id = ledger
            .append_event(&turn_id, &thread_id, "user_turn", r#"{"content": "Hello"}"#)
            .await
            .unwrap();
        assert!(!event_id.is_empty());

        // Get events
        let events = ledger.get_thread_events(&thread_id).await.unwrap();
        assert_eq!(events.len(), 1);

        let event = &events[0];
        assert_eq!(event.kind, "user_turn");
        assert_eq!(event.thread_id, thread_id);
    }

    #[tokio::test]
    async fn test_multiple_events_sequence() {
        let tmp_dir = TempDir::new().unwrap();
        let db_path = tmp_dir.path().join("test.db");
        let db = Db::open(&db_path).await.unwrap();
        let ledger = Ledger::new(db);

        let thread_id = ledger
            .create_thread("test-agent", "cli", "test-session")
            .await
            .unwrap();
        let turn_id = ledger.create_turn(&thread_id, "Test").await.unwrap();

        // Add multiple events
        ledger
            .append_event(&turn_id, &thread_id, "user_turn", r#"{"content": "Hello"}"#)
            .await
            .unwrap();
        ledger
            .append_event(
                &turn_id,
                &thread_id,
                "agent_turn",
                r#"{"content": "Hi there"}"#,
            )
            .await
            .unwrap();
        ledger
            .append_event(&turn_id, &thread_id, "tool_call", r#"{"name": "search"}"#)
            .await
            .unwrap();

        let events = ledger.get_thread_events(&thread_id).await.unwrap();
        assert_eq!(events.len(), 3);

        // Verify sequence order
        assert_eq!(events[0].sequence, 1);
        assert_eq!(events[1].sequence, 2);
        assert_eq!(events[2].sequence, 3);
    }

    #[tokio::test]
    async fn test_different_agent_ids() {
        let tmp_dir = TempDir::new().unwrap();
        let db_path = tmp_dir.path().join("test.db");
        let db = Db::open(&db_path).await.unwrap();
        let ledger = Ledger::new(db);

        let thread1 = ledger
            .create_thread("agent-1", "cli", "session-1")
            .await
            .unwrap();
        let thread2 = ledger
            .create_thread("agent-2", "cli", "session-1")
            .await
            .unwrap();

        // Different agents can have same external_thread_id
        assert_ne!(thread1, thread2);
    }
}
