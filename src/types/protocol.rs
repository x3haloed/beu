use serde::{Deserialize, Serialize};

pub const VERSION: &str = "1.0.0";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Request {
    pub version: String,
    pub command: String,
    pub id: String,
    #[serde(default)]
    pub namespace: Option<String>,
    pub payload: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Response {
    pub version: String,
    pub id: String,
    #[serde(flatten)]
    pub status: ResponseStatus,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum ResponseStatus {
    Ok {
        ok: bool,
        data: serde_json::Value,
    },
    Err {
        ok: bool,
        error: String,
        code: String,
    },
}

impl Response {
    pub fn ok(id: String, data: serde_json::Value) -> Self {
        Self {
            version: VERSION.to_string(),
            id,
            status: ResponseStatus::Ok { ok: true, data },
        }
    }

    pub fn err(id: String, error: String, code: &str) -> Self {
        Self {
            version: VERSION.to_string(),
            id,
            status: ResponseStatus::Err {
                ok: false,
                error,
                code: code.to_string(),
            },
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Command {
    Distill,
    Recall,
    Rebuild,
    Identity,
    Index,
    Status,
}

impl Command {
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "distill" => Some(Command::Distill),
            "recall" => Some(Command::Recall),
            "rebuild" => Some(Command::Rebuild),
            "identity" => Some(Command::Identity),
            "index" => Some(Command::Index),
            "status" => Some(Command::Status),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorCode;

impl ErrorCode {
    pub const INVALID_REQUEST: &str = "INVALID_REQUEST";
    pub const UNKNOWN_COMMAND: &str = "UNKNOWN_COMMAND";
    pub const STORAGE_ERROR: &str = "STORAGE_ERROR";
    pub const MODEL_ERROR: &str = "MODEL_ERROR";
    pub const NOT_FOUND: &str = "NOT_FOUND";
    pub const NAMESPACE_CONFLICT: &str = "NAMESPACE_CONFLICT";
}
