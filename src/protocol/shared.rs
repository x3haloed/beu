use aisdk::core::embedding_model::{EmbeddingModel, EmbeddingModelOptions, EmbeddingModelResponse};
use aisdk::core::DynamicModel;
use aisdk::providers::{Google, OpenAI, OpenAICompatible};
use aisdk::Result as AisdkResult;
use anyhow::{Context, Result};
use async_trait::async_trait;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::Instant;

use crate::observability::{emit, TraceEvent};

#[derive(Debug, Deserialize)]
pub(super) struct RecallPayload {
    #[serde(default)]
    pub(super) namespace: Option<String>,
    pub(super) query: String,
    #[serde(default = "default_limit")]
    pub(super) limit: usize,
}

#[derive(Debug, Deserialize)]
pub(super) struct LedgerListPayload {
    #[serde(default)]
    pub(super) namespace: Option<String>,
    #[serde(default)]
    pub(super) thread_id: Option<String>,
    #[serde(default = "default_limit")]
    pub(super) limit: usize,
}

#[derive(Debug, Deserialize)]
pub(super) struct LedgerSearchPayload {
    #[serde(default)]
    pub(super) namespace: Option<String>,
    pub(super) query: String,
    #[serde(default)]
    pub(super) query_embedding: Option<Vec<f32>>,
    #[serde(default)]
    pub(super) thread_id: Option<String>,
    #[serde(default = "default_limit")]
    pub(super) limit: usize,
}

#[derive(Debug, Deserialize)]
pub(super) struct LedgerGetPayload {
    #[serde(default)]
    pub(super) namespace: Option<String>,
    pub(super) entry_id: String,
}

#[derive(Debug, Deserialize)]
pub(super) struct IndexEntryPayload {
    pub(super) entry_id: String,
    pub(super) source_type: String,
    pub(super) source_id: String,
    pub(super) content: String,
    #[serde(default)]
    pub(super) metadata: Value,
}

#[derive(Debug, Deserialize)]
pub(super) struct IndexPayload {
    #[serde(default)]
    pub(super) namespace: Option<String>,
    #[serde(default)]
    pub(super) embed: bool,
    #[serde(default)]
    pub(super) embedding_provider: Option<EmbeddingProviderPayload>,
    pub(super) entries: Vec<IndexEntryPayload>,
}

#[derive(Debug, Deserialize)]
pub(super) struct EmbeddingProviderPayload {
    pub(super) provider: String,
    pub(super) model: String,
    #[serde(default)]
    pub(super) base_url: Option<String>,
    #[serde(default)]
    pub(super) api_key: Option<String>,
}

#[derive(Debug, Deserialize)]
pub(super) struct DistillPayload {
    #[serde(default)]
    pub(super) namespace: Option<String>,
    #[serde(default)]
    pub(super) thread_id: Option<String>,
    #[serde(default)]
    pub(super) turn_id: Option<String>,
    pub(super) provider: String,
    pub(super) model: String,
    #[serde(default)]
    pub(super) base_url: Option<String>,
    #[serde(default)]
    pub(super) api_key: Option<String>,
    #[serde(default = "default_limit")]
    pub(super) limit: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
pub(super) struct DistillWakePack {
    pub(super) content: String,
    pub(super) summary: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
pub(super) struct DistillFact {
    pub(super) id: String,
    pub(super) claim: String,
    pub(super) support_excerpt: String,
    pub(super) falsifier: String,
    pub(super) citations: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
pub(super) struct DistillInvariant {
    pub(super) id: String,
    pub(super) claim: String,
    pub(super) support_excerpt: String,
    pub(super) falsifier: String,
    pub(super) supersedes_ids: Vec<String>,
    pub(super) derived_from_fact_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
pub(super) struct DistillOutput {
    pub(super) wake_pack: DistillWakePack,
    pub(super) facts: Vec<DistillFact>,
    pub(super) invariant_adds: Vec<DistillInvariant>,
    #[serde(default)]
    pub(super) invariant_removes: Vec<Value>,
    #[serde(default)]
    pub(super) drift_flags: Vec<Value>,
    #[serde(default)]
    pub(super) drift_contradictions: Vec<Value>,
    #[serde(default)]
    pub(super) drift_merges: Vec<Value>,
}

#[derive(Debug, Deserialize)]
pub(super) struct WaitPayload {
    pub(super) token: String,
}

pub(super) fn default_limit() -> usize {
    5
}

pub(super) fn build_ledger_recall_block(
    namespace: &str,
    hits: &[serde_json::Value],
) -> Option<String> {
    if hits.is_empty() {
        return None;
    }
    let mut block = String::from("<ledger_recall>\nInformation from prior runtime history:\n");
    let mut wrote_any = false;
    for hit in hits {
        let citation = hit
            .get("citation")
            .and_then(Value::as_str)
            .or_else(|| hit.get("entry_id").and_then(Value::as_str))
            .or_else(|| hit.get("source_id").and_then(Value::as_str))
            .unwrap_or("");
        let entry_id = hit
            .get("entry_id")
            .and_then(Value::as_str)
            .unwrap_or(citation);
        let content = hit
            .get("content")
            .and_then(Value::as_str)
            .unwrap_or("")
            .replace('\n', " ")
            .trim()
            .to_string();
        if content.is_empty() {
            continue;
        }
        wrote_any = true;
        block.push_str(&format!(
            r#"- [{}] {} ↳ For more, call: `{{ "type": "function_call", "name": "ledger_get", "arguments": "{{\"namespace\":\"{}\",\"entry_id\":\"{}\"}}" }}`
"#,
            citation, content, namespace, entry_id
        ));
    }
    if !wrote_any {
        return None;
    }
    block.push_str("</ledger_recall>");
    Some(block)
}

pub(super) fn build_wake_pack_block(wake_pack: &str) -> Option<String> {
    let content = wake_pack.trim();
    if content.is_empty() {
        return None;
    }
    Some(format!("\n<wake_pack>\n{}\n</wake_pack>", content))
}

pub(super) async fn embed_entries(
    provider: Option<&EmbeddingProviderPayload>,
    entries: &[IndexEntryPayload],
) -> Result<Vec<Option<Vec<f32>>>> {
    let Some(provider) = provider else {
        return Ok(vec![None; entries.len()]);
    };
    if provider.provider.trim().is_empty() || provider.model.trim().is_empty() {
        return Ok(vec![None; entries.len()]);
    }
    let api_key = provider.api_key.clone().unwrap_or_default();
    let base_url = provider.base_url.clone().unwrap_or_default();
    if base_url.trim().is_empty() {
        return Ok(vec![None; entries.len()]);
    }
    let request_id = format!("embed-{}", uuid::Uuid::new_v4());
    let total_chars = entries.iter().map(|entry| entry.content.chars().count()).sum();
    let branch = embeddings_provider_branch(&provider.provider);
    emit(TraceEvent::EmbeddingBatchPrepared {
        request_id: request_id.clone(),
        provider: provider.provider.clone(),
        model: provider.model.clone(),
        entries: entries.len(),
        total_chars,
        base_url_present: !base_url.trim().is_empty(),
        api_key_present: !api_key.trim().is_empty(),
    });
    emit(TraceEvent::ProviderBranchSelected {
        kind: "embeddings".to_string(),
        provider: provider.provider.clone(),
        branch: branch.to_string(),
        model: provider.model.clone(),
        base_url_present: !base_url.trim().is_empty(),
        api_key_present: !api_key.trim().is_empty(),
    });

    let model = build_embeddings_model(&provider.provider, &provider.model, &base_url, &api_key)
        .context("failed to build embeddings provider")?;
    let request = EmbeddingModelOptions::builder()
        .input(entries.iter().map(|entry| entry.content.clone()).collect())
        .dimensions(None)
        .build()
        .context("failed to build embedding request")?;
    emit(TraceEvent::ProviderCallStarted {
        kind: "embeddings".to_string(),
        provider: provider.provider.clone(),
        branch: branch.to_string(),
        model: provider.model.clone(),
        request_id: request_id.clone(),
        input_items: entries.len(),
        prompt_chars: total_chars,
        base_url_present: !base_url.trim().is_empty(),
        api_key_present: !api_key.trim().is_empty(),
    });
    let started = Instant::now();
    let response: Vec<Vec<f32>> = match model.embed(request).await {
        Ok(response) => response,
        Err(e) => {
            emit(TraceEvent::ProviderCallFailed {
                kind: "embeddings".to_string(),
                provider: provider.provider.clone(),
                branch: branch.to_string(),
                model: provider.model.clone(),
                request_id,
                stage: "request".to_string(),
                error: e.to_string(),
                elapsed_ms: started.elapsed().as_millis(),
            });
            return Err(anyhow::anyhow!(e).context("embedding request failed"));
        }
    };
    let output_chars = serde_json::to_string(&response).map(|s| s.chars().count()).unwrap_or(0);
    emit(TraceEvent::ProviderCallSucceeded {
        kind: "embeddings".to_string(),
        provider: provider.provider.clone(),
        branch: branch.to_string(),
        model: provider.model.clone(),
        request_id,
        elapsed_ms: started.elapsed().as_millis(),
        output_chars,
    });
    Ok(response.into_iter().map(Some).collect())
}

#[derive(Debug, Clone)]
pub(super) enum EmbeddingsProviderModel {
    OpenAI(OpenAI<DynamicModel>),
    Google(Google<DynamicModel>),
    OpenAICompatible(OpenAICompatible<DynamicModel>),
}

#[async_trait]
impl EmbeddingModel for EmbeddingsProviderModel {
    async fn embed(&self, input: EmbeddingModelOptions) -> AisdkResult<EmbeddingModelResponse> {
        match self {
            Self::OpenAI(model) => model.embed(input).await,
            Self::Google(model) => model.embed(input).await,
            Self::OpenAICompatible(model) => model.embed(input).await,
        }
    }
}

pub(super) fn build_embeddings_model(
    provider_name: &str,
    model_name: &str,
    base_url: &str,
    api_key: &str,
) -> Result<EmbeddingsProviderModel, anyhow::Error> {
    let provider_name = provider_name.trim().to_lowercase();
    match provider_name.as_str() {
        "openai" => Ok(EmbeddingsProviderModel::OpenAI(
            OpenAI::<DynamicModel>::builder()
                .provider_name("openai")
                .model_name(model_name.to_string())
                .base_url(base_url.to_string())
                .api_key(api_key.to_string())
                .build()
                .map_err(|e| anyhow::anyhow!(e))?,
        )),
        "google" | "gemini" => Ok(EmbeddingsProviderModel::Google(
            Google::<DynamicModel>::builder()
                .provider_name("google")
                .model_name(model_name.to_string())
                .base_url(base_url.to_string())
                .api_key(api_key.to_string())
                .build()
                .map_err(|e| anyhow::anyhow!(e))?,
        )),
        "mistral" | "openrouter" => Ok(EmbeddingsProviderModel::OpenAICompatible(
            OpenAICompatible::<DynamicModel>::builder()
                .provider_name(provider_name)
                .model_name(model_name.to_string())
                .base_url(base_url.to_string())
                .api_key(api_key.to_string())
                .build()
                .map_err(|e| anyhow::anyhow!(e))?,
        )),
        _ => Ok(EmbeddingsProviderModel::OpenAICompatible(
            OpenAICompatible::<DynamicModel>::builder()
                .provider_name(provider_name)
                .model_name(model_name.to_string())
                .base_url(base_url.to_string())
                .api_key(api_key.to_string())
                .build()
                .map_err(|e| anyhow::anyhow!(e))?,
        )),
    }
}

pub(super) fn embeddings_provider_branch(provider_name: &str) -> &'static str {
    match provider_name.trim().to_lowercase().as_str() {
        "openai" => "openai",
        "google" | "gemini" => "google",
        "mistral" | "openrouter" => "openai_compatible",
        _ => "openai_compatible",
    }
}
