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
