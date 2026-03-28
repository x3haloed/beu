use anyhow::{Context, Result};
use beu::storage::create_db;
use directories::ProjectDirs;
use std::path::PathBuf;
use tracing::info;
use uuid::Uuid;

fn get_data_dir() -> PathBuf {
    ProjectDirs::from("com", "beu", "beu")
        .map(|dirs| dirs.data_dir().to_path_buf())
        .unwrap_or_else(|| PathBuf::from("./beu_data"))
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();

    let data_dir = get_data_dir();
    std::fs::create_dir_all(&data_dir).context("Failed to create data directory")?;

    let db_path = data_dir.join("memory.db");
    info!(path = %db_path.display(), "Opening database");

    let db = create_db(&db_path)
        .await
        .context("Failed to open database")?;

    info!("Database initialized");

    let ledger = beu::storage::ledger::Ledger::new(db);

    // Use unique session to avoid UNIQUE constraint
    let session_id = Uuid::new_v4().to_string();
    let thread_id = ledger
        .create_thread("default", "cli", &session_id)
        .await
        .context("Failed to create thread")?;

    let turn_id = ledger
        .create_turn(&thread_id, "Hello")
        .await
        .context("Failed to create turn")?;

    ledger
        .append_event(&turn_id, &thread_id, "user_turn", r#"{"content": "Hello"}"#)
        .await
        .context("Failed to append event")?;

    let events = ledger
        .get_thread_events(&thread_id)
        .await
        .context("Failed to get events")?;

    info!(event_count = %events.len(), "Thread events retrieved");

    Ok(())
}
