from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

from ._shared import (
    AISDK_PROVIDER_ALIASES,
    DEFAULT_DISTILL_HOOK_THRESHOLD,
    HERMES_HOME,
    SUPPORTED_EMBEDDING_PROVIDERS,
    logger,
)


_ROOT = None

BEU_CONFIG_ENV = "BEU_CONFIG_PATH"
BEU_EMBEDDING_ENV_KEYS = {
    "provider": "BEU_EMBEDDINGS_PROVIDER",
    "base_url": "BEU_EMBEDDINGS_BASE_URL",
    "api_key": "BEU_EMBEDDINGS_API_KEY",
    "model": "BEU_EMBEDDINGS_MODEL",
}
BEU_DEFAULT_CONFIG_FILENAMES = ("beu.yaml", "beu.yml")


def _deep_merge_dicts(base: dict, updates: dict) -> dict:
    merged = dict(base or {})
    for key, value in (updates or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged.get(key, {}), value)
        else:
            merged[key] = value
    return merged


def _beu_config_candidate_paths() -> list[Path]:
    candidate_paths = []
    env_path = os.environ.get(BEU_CONFIG_ENV, "").strip()
    if env_path:
        candidate_paths.append(Path(env_path).expanduser())
    adapter_dir = Path(__file__).resolve().parent
    candidate_paths.extend(adapter_dir / name for name in BEU_DEFAULT_CONFIG_FILENAMES)
    return candidate_paths


def _resolve_beu_config_path(prefer_existing: bool = True) -> Path:
    candidate_paths = _beu_config_candidate_paths()
    if prefer_existing:
        for path in candidate_paths:
            if path.is_file():
                return path
    return candidate_paths[0] if candidate_paths else Path(__file__).resolve().parent / "beu.yaml"


def _read_beu_config_data(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("Failed to read BeU config %s: %s", path, exc)
        return {}
    if isinstance(data, dict):
        return data
    logger.warning("BeU config %s must contain a mapping at the top level", path)
    return {}


def _load_beu_config_file() -> dict:
    return _read_beu_config_data(_resolve_beu_config_path(prefer_existing=True))


def _collect_beu_embedding_settings() -> dict:
    config = _load_beu_config_file()
    embeddings_cfg = {}
    if isinstance(config.get("embeddings"), dict):
        embeddings_cfg.update(config["embeddings"])
    for key in ("provider", "base_url", "api_key", "model"):
        value = config.get(key)
        if value not in (None, "") and key not in embeddings_cfg:
            embeddings_cfg[key] = value
    for key, env_name in BEU_EMBEDDING_ENV_KEYS.items():
        value = os.environ.get(env_name, "").strip()
        if value:
            embeddings_cfg[key] = value
    cleaned = {}
    for key, value in embeddings_cfg.items():
        text_value = str(value or "").strip()
        if text_value:
            cleaned[key] = text_value
    return cleaned


def _resolve_embedding_provider(*, namespace: str, kwargs: dict) -> Optional[dict]:
    local_settings = _ROOT._collect_beu_embedding_settings()
    if local_settings:
        provider = str(local_settings.get("provider") or "").strip().lower()
        base_url = str(local_settings.get("base_url") or "").strip().rstrip("/")
        api_key = str(local_settings.get("api_key") or "").strip()
        model = str(local_settings.get("model") or "").strip()
        if not provider and base_url:
            provider = "custom"
        if provider and model:
            embedding_provider = {"provider": provider, "model": model}
            if base_url:
                embedding_provider["base_url"] = base_url
            if api_key:
                embedding_provider["api_key"] = api_key
            return embedding_provider
        if any(local_settings.values()):
            logger.warning("BeU embeddings config is present but incomplete; falling back to Hermes provider resolution")
    try:
        from hermes_cli.runtime_provider import resolve_requested_provider, resolve_runtime_provider
    except Exception as exc:
        logger.warning("Embedding provider resolution unavailable: %s", exc)
        return None
    requested = kwargs.get("provider") or resolve_requested_provider()
    try:
        runtime = resolve_runtime_provider(requested=requested)
    except Exception as exc:
        logger.debug("Failed to resolve Hermes runtime provider for embeddings: %s", exc)
        runtime = None
    if not runtime:
        return None
    resolved_provider = str(runtime.get("provider") or "").strip().lower()
    resolved_base_url = str(runtime.get("base_url") or "").strip()
    resolved_api_key = str(runtime.get("api_key") or runtime.get("api") or "").strip()
    resolved_model = str(runtime.get("model") or "").strip()
    if resolved_provider not in SUPPORTED_EMBEDDING_PROVIDERS and not resolved_base_url:
        return None
    if resolved_provider == "custom" and not resolved_base_url:
        return None
    if not resolved_model:
        return None
    embedding_provider = {"provider": resolved_provider or "custom", "model": resolved_model}
    if resolved_base_url:
        embedding_provider["base_url"] = resolved_base_url
    if resolved_api_key:
        embedding_provider["api_key"] = resolved_api_key
    return embedding_provider


def _provider_payload_from_config_entry(entry: dict[str, Any]) -> dict[str, Any]:
    provider = str(entry.get("provider") or "").strip().lower().replace(" ", "-")
    model = str(entry.get("model") or entry.get("default") or "").strip()
    if not provider or not model or provider not in AISDK_PROVIDER_ALIASES:
        return {}
    payload: dict[str, Any] = {"provider": AISDK_PROVIDER_ALIASES[provider], "model": model}
    base_url = str(entry.get("base_url") or "").strip()
    api_key = str(entry.get("api_key") or entry.get("api") or "").strip()
    if base_url:
        payload["base_url"] = base_url
    if api_key:
        payload["api_key"] = api_key
    return payload


def _candidate_distill_payloads() -> list[dict[str, Any]]:
    try:
        from hermes_cli.config import load_config
    except Exception as exc:
        logger.warning("Failed to import Hermes config loader for distill: %s", exc)
        return []
    try:
        config = load_config() or {}
    except Exception as exc:
        logger.warning("Failed to load Hermes config for distill: %s", exc)
        return []
    candidates: list[dict[str, Any]] = []
    model_cfg = config.get("model")
    if isinstance(model_cfg, dict):
        payload = _provider_payload_from_config_entry(model_cfg)
        if payload:
            candidates.append(payload)
    elif isinstance(model_cfg, str):
        provider_cfg = config.get("provider")
        if isinstance(provider_cfg, str):
            payload = _provider_payload_from_config_entry(
                {
                    "provider": provider_cfg,
                    "model": model_cfg,
                    "base_url": config.get("base_url"),
                    "api_key": config.get("api_key"),
                }
            )
            if payload:
                candidates.append(payload)
    fallback_model = config.get("fallback_model")
    if isinstance(fallback_model, dict):
        payload = _provider_payload_from_config_entry(fallback_model)
        if payload:
            candidates.append(payload)
    custom_providers = config.get("custom_providers")
    if isinstance(custom_providers, list):
        for entry in custom_providers:
            if isinstance(entry, dict):
                payload = _provider_payload_from_config_entry(entry)
                if payload:
                    candidates.append(payload)
    return candidates
