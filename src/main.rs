use anyhow::Result;
use beu::storage::create_db;
use directories::ProjectDirs;
use std::path::PathBuf;

fn get_data_dir() -> PathBuf {
    ProjectDirs::from("com", "beu", "beu")
        .map(|dirs| dirs.data_dir().to_path_buf())
        .unwrap_or_else(|| PathBuf::from("./beu_data"))
}

#[tokio::main]
async fn main() -> Result<()> {
    let data_dir = get_data_dir();
    std::fs::create_dir_all(&data_dir)?;
    
    let db_path = data_dir.join("memory.db");
    println!("Opening database at: {:?}", db_path);
    
    let db = create_db(&db_path).await?;
    
    println!("Database initialized");
    
    let ledger = beu::storage::ledger::Ledger::new(db);
    let thread_id = ledger.create_thread("default", "cli", "test-session").await?;
    let turn_id = ledger.create_turn(&thread_id, "Hello").await?;
    ledger.append_event(&turn_id, &thread_id, "user_turn", r#"{"content": "Hello"}"#).await?;
    let events = ledger.get_thread_events(&thread_id).await?;
    println!("Thread has {} events", events.len());
    
    Ok(())
}