use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Event {
    pub id: String,
    pub turn_id: String,
    pub thread_id: String,
    pub sequence: i64,
    pub kind: String,
    pub payload: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Turn {
    pub id: String,
    pub thread_id: String,
    pub status: String,
    pub user_message: String,
    pub assistant_message: Option<String>,
    pub error: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LedgerEntryKind {
    UserTurn,
    AgentTurn,
    ToolCall,
    ToolResult,
    Error,
    TraceSummary,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LedgerEntry {
    pub entry_id: String,
    pub kind: LedgerEntryKind,
    pub content: String,
    pub citation: String,
    pub created_at: String,
}
