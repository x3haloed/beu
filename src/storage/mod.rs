pub mod ledger;
pub mod migrations;

use libsql::{Builder, Connection, Database};
use std::path::Path;
use tokio::sync::Mutex;

pub struct Db {
    database: Database,
    write_lock: Mutex<()>,
}

impl Db {
    pub async fn open<P: AsRef<Path>>(path: P) -> anyhow::Result<Self> {
        let database = Builder::new_local(path.as_ref()).build().await?;
        let db = Self {
            database,
            write_lock: Mutex::new(()),
        };
        db.initialize().await?;
        Ok(db)
    }

    pub async fn connect(&self) -> anyhow::Result<Connection> {
        let conn = self.database.connect()?;
        Ok(conn)
    }

    pub async fn write_connection(&self) -> anyhow::Result<(tokio::sync::MutexGuard<'_, ()>, Connection)> {
        let guard = self.write_lock.lock().await;
        let conn = self.connect().await?;
        Ok((guard, conn))
    }

    pub async fn initialize(&self) -> anyhow::Result<()> {
        migrations::run(self).await?;
        Ok(())
    }
}

pub async fn create_db<P: AsRef<Path>>(path: P) -> anyhow::Result<Db> {
    let db = Db::open(path).await?;
    Ok(db)
}