use super::*;
use aisdk::core::DynamicModel;
use aisdk::core::LanguageModelRequest;
use aisdk::providers::{AmazonBedrock, Google, Groq, OpenAI, OpenAICompatible, TogetherAI, XAI};
use anyhow::{Context, Result};
use std::time::Instant;

use crate::observability::{emit, TraceEvent};

impl Protocol {
    fn build_distill_model(
        parsed: &DistillPayload,
    ) -> Result<(String, String, Option<String>, String)> {
        let provider = parsed.provider.trim().to_lowercase();
        let model = parsed.model.trim().to_string();
        if provider.is_empty() || model.is_empty() {
            return Err(anyhow::anyhow!("distill requires provider and model"));
        }
        let base_url = parsed.base_url.clone().and_then(|value| {
            let trimmed = value.trim().to_string();
            if trimmed.is_empty() {
                None
            } else {
                Some(trimmed)
            }
        });
        let api_key = parsed
            .api_key
            .clone()
            .unwrap_or_else(|| "no-key-required".to_string());

        Ok((provider, model, base_url, api_key))
    }

    async fn load_thread_history(
        db: &Db,
        namespace: &str,
        thread_id: &str,
        limit: usize,
    ) -> Result<Vec<Value>> {
        let (_guard, conn) = db
            .write_connection()
            .await
            .context("failed to open database connection")?;
        let mut stmt = conn
            .prepare(
                "SELECT m.id, m.entry_type, m.thread_id, m.turn_id, m.source_type, m.source_id, COALESCE(m.summary, t.content) AS content, m.citation, m.payload, m.updated_at
                 FROM ledger_entries m
                 JOIN ledger_entry_chunks t ON t.entry_id = m.id
                 WHERE m.namespace_id = ? AND m.thread_id = ? AND m.deleted_at IS NULL AND m.entry_type IN ('user_turn', 'assistant_turn', 'tool_result')
                 ORDER BY m.updated_at ASC LIMIT ?",
            )
            .await
            .context("failed to prepare thread history query")?;
        let mut rows = stmt
            .query(libsql::params![namespace, thread_id, limit as i64])
            .await
            .context("failed to query thread history")?;
        let mut entries = Vec::new();
        while let Some(row) = rows.next().await.context("failed to read history row")? {
            entries.push(serde_json::json!({
                "entry_id": row.get::<String>(0).unwrap_or_default(),
                "kind": row.get::<String>(1).unwrap_or_default(),
                "thread_id": row.get::<Option<String>>(2).unwrap_or(None),
                "turn_id": row.get::<Option<String>>(3).unwrap_or(None),
                "source_type": row.get::<String>(4).unwrap_or_default(),
                "source_id": row.get::<String>(5).unwrap_or_default(),
                "content": row.get::<String>(6).unwrap_or_default(),
                "citation": row.get::<Option<String>>(7).unwrap_or(None),
                "payload": row.get::<String>(8).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()),
                "created_at": row.get::<String>(9).unwrap_or_default(),
            }));
        }
        Ok(entries)
    }

    fn extract_prior_wake_pack(history: &[Value]) -> Value {
        for entry in history.iter().rev() {
            if let Some(payload) = entry.get("payload").and_then(Value::as_object) {
                if let Some(wake_pack) = payload.get("wake_pack") {
                    return wake_pack.clone();
                }
            }
        }
        Value::Object(serde_json::Map::new())
    }

    fn extract_active_invariants(history: &[Value]) -> Vec<Value> {
        let mut invariants = Vec::new();
        for entry in history {
            if let Some(payload) = entry.get("payload").and_then(Value::as_object) {
                for key in ["invariant_adds", "invariants"] {
                    if let Some(values) = payload.get(key).and_then(Value::as_array) {
                        invariants.extend(values.iter().cloned());
                    }
                }
            }
        }
        invariants
            .into_iter()
            .rev()
            .take(12)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect()
    }

    pub(super) fn distill_provider_branch(provider: &str) -> Option<&'static str> {
        match provider.trim().to_lowercase().as_str() {
            "openai" => Some("openai"),
            "google" | "gemini" => Some("google"),
            "mistral" | "openrouter" | "custom" => Some("openai_compatible"),
            "groq" => Some("groq"),
            "amazon_bedrock" => Some("amazon_bedrock"),
            "togetherai" => Some("togetherai"),
            "xai" => Some("xai"),
            other if !other.is_empty() => None,
            _ => None,
        }
    }

    async fn run_distill_model(
        provider: &str,
        model_name: &str,
        base_url: Option<&str>,
        api_key: &str,
        thread_history: &[Value],
        prior_wake_pack: &Value,
        active_invariants: &[Value],
    ) -> Result<DistillOutput> {
        let prompt = serde_json::json!({
            "thread_history": thread_history,
            "prior_wake_pack": prior_wake_pack,
            "active_invariants": active_invariants,
        });
        let prompt_text = prompt.to_string();
        let system = "You are BeU's compressor model. Return only JSON that matches the requested schema. Keep claims invariant-style, not policy and not narration.";
        let branch = Self::distill_provider_branch(provider).unwrap_or("unsupported");
        let request_id = format!("distill-{}", uuid::Uuid::new_v4());
        let prompt_chars = prompt_text.chars().count() + system.chars().count();

        emit(TraceEvent::ProviderBranchSelected {
            kind: "llm".to_string(),
            provider: provider.to_string(),
            branch: branch.to_string(),
            model: model_name.to_string(),
            base_url_present: base_url.is_some(),
            api_key_present: !api_key.trim().is_empty(),
        });

        macro_rules! run_branch {
            ($branch_name:expr, $model:expr) => {{
                let started = Instant::now();
                emit(TraceEvent::ProviderCallStarted {
                    kind: "llm".to_string(),
                    provider: provider.to_string(),
                    branch: $branch_name.to_string(),
                    model: model_name.to_string(),
                    request_id: request_id.clone(),
                    input_items: thread_history.len(),
                    prompt_chars,
                    base_url_present: base_url.is_some(),
                    api_key_present: !api_key.trim().is_empty(),
                });
                let response = LanguageModelRequest::builder()
                    .model($model)
                    .system(system)
                    .prompt(prompt_text.clone())
                    .schema::<DistillOutput>()
                    .build()
                    .generate_text()
                    .await
                    .map_err(|e| {
                        emit(TraceEvent::ProviderCallFailed {
                            kind: "llm".to_string(),
                            provider: provider.to_string(),
                            branch: $branch_name.to_string(),
                            model: model_name.to_string(),
                            request_id: request_id.clone(),
                            stage: "request".to_string(),
                            error: e.to_string(),
                            elapsed_ms: started.elapsed().as_millis(),
                        });
                        anyhow::anyhow!(e).context("distill generation failed")
                    })?;
                let parsed = response.into_schema::<DistillOutput>().map_err(|e| {
                    emit(TraceEvent::ProviderCallFailed {
                        kind: "llm".to_string(),
                        provider: provider.to_string(),
                        branch: $branch_name.to_string(),
                        model: model_name.to_string(),
                        request_id: request_id.clone(),
                        stage: "parse".to_string(),
                        error: e.to_string(),
                        elapsed_ms: started.elapsed().as_millis(),
                    });
                    anyhow::anyhow!(e).context("failed to parse distill output")
                })?;
                emit(TraceEvent::ProviderCallSucceeded {
                    kind: "llm".to_string(),
                    provider: provider.to_string(),
                    branch: $branch_name.to_string(),
                    model: model_name.to_string(),
                    request_id: request_id.clone(),
                    elapsed_ms: started.elapsed().as_millis(),
                    output_chars: serde_json::to_string(&parsed)
                        .map(|s| s.chars().count())
                        .unwrap_or(0),
                });
                Ok(parsed)
            }};
        }

        match branch {
            "openai" => {
                let mut builder = OpenAI::<DynamicModel>::builder()
                    .provider_name("openai")
                    .model_name(model_name.to_string())
                    .api_key(api_key.to_string());
                if let Some(url) = base_url {
                    builder = builder.base_url(url.to_string());
                }
                run_branch!("openai", builder.build().map_err(|e| anyhow::anyhow!(e))?)
            }
            "google" => {
                let mut builder = Google::<DynamicModel>::builder()
                    .provider_name("google")
                    .model_name(model_name.to_string())
                    .api_key(api_key.to_string());
                if let Some(url) = base_url {
                    builder = builder.base_url(url.to_string());
                }
                run_branch!("google", builder.build().map_err(|e| anyhow::anyhow!(e))?)
            }
            "openai_compatible" => {
                let mut builder = OpenAICompatible::<DynamicModel>::builder()
                    .provider_name(provider.to_string())
                    .model_name(model_name.to_string())
                    .api_key(api_key.to_string());
                if let Some(url) = base_url {
                    builder = builder.base_url(url.to_string());
                }
                run_branch!(
                    "openai_compatible",
                    builder.build().map_err(|e| anyhow::anyhow!(e))?
                )
            }
            "groq" => {
                let mut builder = Groq::<DynamicModel>::builder()
                    .provider_name("groq")
                    .model_name(model_name.to_string())
                    .api_key(api_key.to_string());
                if let Some(url) = base_url {
                    builder = builder.base_url(url.to_string());
                }
                run_branch!("groq", builder.build().map_err(|e| anyhow::anyhow!(e))?)
            }
            "amazon_bedrock" => {
                let mut builder = AmazonBedrock::<DynamicModel>::builder()
                    .provider_name("amazon_bedrock")
                    .model_name(model_name.to_string())
                    .api_key(api_key.to_string());
                if let Some(url) = base_url {
                    builder = builder.base_url(url.to_string());
                }
                run_branch!(
                    "amazon_bedrock",
                    builder.build().map_err(|e| anyhow::anyhow!(e))?
                )
            }
            "togetherai" => {
                let mut builder = TogetherAI::<DynamicModel>::builder()
                    .provider_name("togetherai")
                    .model_name(model_name.to_string())
                    .api_key(api_key.to_string());
                if let Some(url) = base_url {
                    builder = builder.base_url(url.to_string());
                }
                run_branch!("togetherai", builder.build().map_err(|e| anyhow::anyhow!(e))?)
            }
            "xai" => {
                let mut builder = XAI::<DynamicModel>::builder()
                    .provider_name("xai")
                    .model_name(model_name.to_string())
                    .api_key(api_key.to_string());
                if let Some(url) = base_url {
                    builder = builder.base_url(url.to_string());
                }
                run_branch!("xai", builder.build().map_err(|e| anyhow::anyhow!(e))?)
            }
            _ => {
                emit(TraceEvent::ProviderCallFailed {
                    kind: "llm".to_string(),
                    provider: provider.to_string(),
                    branch: branch.to_string(),
                    model: model_name.to_string(),
                    request_id,
                    stage: "branch".to_string(),
                    error: format!("unsupported distill provider: {provider}"),
                    elapsed_ms: 0,
                });
                Err(anyhow::anyhow!("unsupported distill provider: {}", provider))
            }
        }
    }

    pub(super) async fn handle_distill(
        id: String,
        namespace: String,
        payload: Value,
        db: &Db,
    ) -> Response {
        let parsed: DistillPayload = match serde_json::from_value(payload.clone()) {
            Ok(value) => value,
            Err(e) => {
                return Response::err(
                    id,
                    format!("Invalid distill payload: {}", e),
                    ErrorCode::INVALID_REQUEST,
                );
            }
        };
        let ns = parsed.namespace.clone().unwrap_or(namespace);
        let thread_id = parsed.thread_id.clone().unwrap_or_else(|| ns.clone());
        let turn_id = parsed.turn_id.clone().unwrap_or_else(|| id.clone());
        let (provider, model_name, base_url, api_key) = match Self::build_distill_model(&parsed) {
            Ok(model) => model,
            Err(e) => {
                return Response::err(id, format!("Model error: {}", e), ErrorCode::MODEL_ERROR);
            }
        };
        let thread_history: Vec<Value> =
            match Self::load_thread_history(db, &ns, &thread_id, parsed.limit).await {
                Ok(history) => history,
                Err(e) => {
                    return Response::err(
                        id,
                        format!("Storage error: {}", e),
                        ErrorCode::STORAGE_ERROR,
                    );
                }
            };
        let prior_wake_pack = Self::extract_prior_wake_pack(&thread_history);
        let active_invariants = Self::extract_active_invariants(&thread_history);
        let output = match Self::run_distill_model(
            &provider,
            &model_name,
            base_url.as_deref(),
            &api_key,
            &thread_history,
            &prior_wake_pack,
            &active_invariants,
        )
        .await
        {
            Ok(output) => output,
            Err(e) => {
                return Response::err(id, format!("Model error: {}", e), ErrorCode::MODEL_ERROR);
            }
        };
        let now_payload = serde_json::json!({
            "thread_id": thread_id,
            "turn_id": turn_id,
            "thread_history": thread_history,
            "prior_wake_pack": prior_wake_pack,
            "active_invariants": active_invariants,
            "wake_pack": output.wake_pack,
            "facts": output.facts,
            "invariant_adds": output.invariant_adds,
            "invariant_removes": output.invariant_removes,
            "drift_flags": output.drift_flags,
            "drift_contradictions": output.drift_contradictions,
            "drift_merges": output.drift_merges,
        });
        let (item, text) = build_memory_item(
            &ns,
            "wake_pack",
            "distill",
            &id,
            Some("Distilled memory".to_string()),
            Some("Memory distilled from thread history".to_string()),
            Some(id.clone()),
            now_payload,
            10,
            None,
        );
        if let Err(e) = db.upsert_memory_item(item, text).await {
            return Response::err(
                id,
                format!("Storage error: {}", e),
                ErrorCode::STORAGE_ERROR,
            );
        }
        Response::ok(
            id,
            serde_json::json!({
                "message": "distill stored",
                "namespace": ns,
                "thread_id": thread_id,
                "turn_id": turn_id,
            }),
        )
    }
}
