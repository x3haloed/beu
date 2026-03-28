pub mod ledger;
pub mod migrations;

use libsql::{Builder, Connection, Database};
use std::path::Path;
use tokio::sync::Mutex;
use tracing::{debug, error};

pub struct Db {
    database: Database,
    write_lock: Mutex<()>,
}

impl Db {
    pub async fn open<P: AsRef<Path>>(path: P) -> anyhow::Result<Self> {
        let path_str = path.as_ref().to_string_lossy().to_string();
        debug!(path = %path_str, "Opening database");
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
        debug!("Opening in-memory database");
        let database = Builder::new_local(":memory:").build().await?;
        let db = Self {
            database,
            write_lock: Mutex::new(()),
        };
        db.initialize().await?;
        debug!("In-memory database initialized");
        Ok(db)
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
}

pub async fn create_db<P: AsRef<Path>>(path: P) -> anyhow::Result<Db> {
    Db::open(path).await
}
