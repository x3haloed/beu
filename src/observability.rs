use std::env;
use serde::Serialize;
use tracing_subscriber::{EnvFilter, fmt, layer::SubscriberExt, util::SubscriberInitExt};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LogFormat {
    Human,
    Json,
}

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum TraceEvent {
    ProtocolRequestReceived {
        request_id: String,
        command: String,
        namespace: String,
        bytes: usize,
    },
    ProtocolRequestParsed {
        request_id: String,
        command: String,
        namespace: String,
    },
    ProtocolRequestFailed {
        request_id: String,
        command: String,
        namespace: String,
        error: String,
    },
    ProtocolResponseSent {
        request_id: String,
        ok: bool,
        bytes: usize,
    },
    StorageOpened {
        path: String,
        in_memory: bool,
    },
    StorageInitialized,
    StorageUpsertStarted {
        entry_id: String,
        namespace_id: String,
        entry_type: String,
        source_type: String,
    },
    StorageUpsertCompleted {
        entry_id: String,
    },
    ProviderBranchSelected {
        kind: String,
        provider: String,
        branch: String,
        model: String,
        base_url_present: bool,
        api_key_present: bool,
    },
    ProviderCallStarted {
        kind: String,
        provider: String,
        branch: String,
        model: String,
        request_id: String,
        input_items: usize,
        prompt_chars: usize,
        base_url_present: bool,
        api_key_present: bool,
    },
    ProviderCallSucceeded {
        kind: String,
        provider: String,
        branch: String,
        model: String,
        request_id: String,
        elapsed_ms: u128,
        output_chars: usize,
    },
    ProviderCallFailed {
        kind: String,
        provider: String,
        branch: String,
        model: String,
        request_id: String,
        stage: String,
        error: String,
        elapsed_ms: u128,
    },
    EmbeddingBatchPrepared {
        request_id: String,
        provider: String,
        model: String,
        entries: usize,
        total_chars: usize,
        base_url_present: bool,
        api_key_present: bool,
    },
}

fn env_flag(name: &str) -> bool {
    matches!(
        env::var(name).ok().as_deref().map(str::trim).map(str::to_lowercase),
        Some(value) if matches!(value.as_str(), "1" | "true" | "yes" | "on")
    )
}

fn log_format() -> LogFormat {
    match env::var("BEU_LOG_FORMAT")
        .or_else(|_| env::var("RUST_LOG_STYLE"))
        .unwrap_or_default()
        .trim()
        .to_lowercase()
        .as_str()
    {
        "json" => LogFormat::Json,
        _ => LogFormat::Human,
    }
}

fn default_filter() -> &'static str {
    "warn"
}

pub fn trace_payloads_enabled() -> bool {
    env_flag("BEU_TRACE_PAYLOADS")
}

pub fn init() {
    let filter = env::var("BEU_LOG_LEVEL")
        .ok()
        .and_then(|value| EnvFilter::try_new(value).ok())
        .or_else(|| EnvFilter::try_from_default_env().ok())
        .unwrap_or_else(|| EnvFilter::new(default_filter()));

    let format = log_format();
    match format {
        LogFormat::Json => {
            let subscriber = tracing_subscriber::registry()
                .with(filter)
                .with(fmt::layer().json().with_writer(std::io::stderr));
            let _ = subscriber.try_init();
        }
        LogFormat::Human => {
            let subscriber = tracing_subscriber::registry()
                .with(filter)
                .with(
                    fmt::layer()
                        .with_writer(std::io::stderr)
                        .with_target(true)
                        .with_thread_names(false)
                        .with_thread_ids(false),
                );
            let _ = subscriber.try_init();
        }
    }
}

pub fn emit(event: TraceEvent) {
    match event {
        TraceEvent::ProtocolRequestReceived {
            request_id,
            command,
            namespace,
            bytes,
        } => tracing::info!(
            target: "beu.event",
            event = "protocol_request_received",
            request_id = %request_id,
            command = %command,
            namespace = %namespace,
            bytes,
            "structured event"
        ),
        TraceEvent::ProtocolRequestParsed {
            request_id,
            command,
            namespace,
        } => tracing::info!(
            target: "beu.event",
            event = "protocol_request_parsed",
            request_id = %request_id,
            command = %command,
            namespace = %namespace,
            "structured event"
        ),
        TraceEvent::ProtocolRequestFailed {
            request_id,
            command,
            namespace,
            error,
        } => tracing::warn!(
            target: "beu.event",
            event = "protocol_request_failed",
            request_id = %request_id,
            command = %command,
            namespace = %namespace,
            error = %error,
            "structured event"
        ),
        TraceEvent::ProtocolResponseSent {
            request_id,
            ok,
            bytes,
        } => tracing::info!(
            target: "beu.event",
            event = "protocol_response_sent",
            request_id = %request_id,
            ok,
            bytes,
            "structured event"
        ),
        TraceEvent::StorageOpened { path, in_memory } => tracing::info!(
            target: "beu.event",
            event = "storage_opened",
            path = %path,
            in_memory,
            "structured event"
        ),
        TraceEvent::StorageInitialized => tracing::info!(
            target: "beu.event",
            event = "storage_initialized",
            "structured event"
        ),
        TraceEvent::StorageUpsertStarted {
            entry_id,
            namespace_id,
            entry_type,
            source_type,
        } => tracing::debug!(
            target: "beu.event",
            event = "storage_upsert_started",
            entry_id = %entry_id,
            namespace_id = %namespace_id,
            entry_type = %entry_type,
            source_type = %source_type,
            "structured event"
        ),
        TraceEvent::StorageUpsertCompleted { entry_id } => tracing::debug!(
            target: "beu.event",
            event = "storage_upsert_completed",
            entry_id = %entry_id,
            "structured event"
        ),
        TraceEvent::ProviderBranchSelected {
            kind,
            provider,
            branch,
            model,
            base_url_present,
            api_key_present,
        } => tracing::info!(
            target: "beu.event",
            event = "provider_branch_selected",
            kind = %kind,
            provider = %provider,
            branch = %branch,
            model = %model,
            base_url_present,
            api_key_present,
            "structured event"
        ),
        TraceEvent::ProviderCallStarted {
            kind,
            provider,
            branch,
            model,
            request_id,
            input_items,
            prompt_chars,
            base_url_present,
            api_key_present,
        } => tracing::info!(
            target: "beu.event",
            event = "provider_call_started",
            kind = %kind,
            provider = %provider,
            branch = %branch,
            model = %model,
            request_id = %request_id,
            input_items,
            prompt_chars,
            base_url_present,
            api_key_present,
            "structured event"
        ),
        TraceEvent::ProviderCallSucceeded {
            kind,
            provider,
            branch,
            model,
            request_id,
            elapsed_ms,
            output_chars,
        } => tracing::info!(
            target: "beu.event",
            event = "provider_call_succeeded",
            kind = %kind,
            provider = %provider,
            branch = %branch,
            model = %model,
            request_id = %request_id,
            elapsed_ms,
            output_chars,
            "structured event"
        ),
        TraceEvent::ProviderCallFailed {
            kind,
            provider,
            branch,
            model,
            request_id,
            stage,
            error,
            elapsed_ms,
        } => tracing::warn!(
            target: "beu.event",
            event = "provider_call_failed",
            kind = %kind,
            provider = %provider,
            branch = %branch,
            model = %model,
            request_id = %request_id,
            stage = %stage,
            error = %error,
            elapsed_ms,
            "structured event"
        ),
        TraceEvent::EmbeddingBatchPrepared {
            request_id,
            provider,
            model,
            entries,
            total_chars,
            base_url_present,
            api_key_present,
        } => tracing::info!(
            target: "beu.event",
            event = "embedding_batch_prepared",
            request_id = %request_id,
            provider = %provider,
            model = %model,
            entries,
            total_chars,
            base_url_present,
            api_key_present,
            "structured event"
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::TraceEvent;

    #[test]
    fn trace_event_serializes_with_stable_event_name() {
        let event = TraceEvent::ProtocolRequestReceived {
            request_id: "req-1".to_string(),
            command: "index".to_string(),
            namespace: "agent-123".to_string(),
            bytes: 42,
        };
        let json = serde_json::to_value(event).expect("serialize trace event");
        assert_eq!(json["event"], "protocol_request_received");
        assert_eq!(json["request_id"], "req-1");
        assert_eq!(json["command"], "index");
        assert_eq!(json["namespace"], "agent-123");
        assert_eq!(json["bytes"], 42);
    }

    #[test]
    fn provider_call_event_serializes_with_stable_event_name() {
        let event = TraceEvent::ProviderCallFailed {
            kind: "distill".to_string(),
            provider: "openai".to_string(),
            branch: "openai".to_string(),
            model: "gpt-5".to_string(),
            request_id: "req-2".to_string(),
            stage: "parse".to_string(),
            error: "bad schema".to_string(),
            elapsed_ms: 17,
        };
        let json = serde_json::to_value(event).expect("serialize trace event");
        assert_eq!(json["event"], "provider_call_failed");
        assert_eq!(json["kind"], "distill");
        assert_eq!(json["stage"], "parse");
        assert_eq!(json["elapsed_ms"], 17);
    }
}
