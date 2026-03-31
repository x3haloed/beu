from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_BEU_BINARY = "beu"
HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
DEFAULT_NAMESPACE = "default"
DEFAULT_DISTILL_HOOK_THRESHOLD = 12
SUPPORTED_EMBEDDING_PROVIDERS = {
    "openai",
    "openrouter",
    "custom",
    "google",
    "mistral",
}

AISDK_PROVIDER_ALIASES = {
    "openai": "openai",
    "github-copilot": "openai",
    "github": "openai",
    "github-models": "openai",
    "copilot": "openai",
    "copilot-acp": "openai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "claude-code": "anthropic",
    "google": "google",
    "gemini": "google",
    "mistral": "mistral",
    "nous": "openai_compatible",
    "openrouter": "openai_compatible",
    "groq": "groq",
    "openai-compatible": "openai_compatible",
    "openai_compatible": "openai_compatible",
    "openai compatible": "openai_compatible",
    "amazon-bedrock": "amazon_bedrock",
    "amazon_bedrock": "amazon_bedrock",
    "togetherai": "togetherai",
    "xai": "xai",
    "custom": "openai_compatible",
    "zai": "openai_compatible",
    "glm": "openai_compatible",
    "z-ai": "openai_compatible",
    "z.ai": "openai_compatible",
    "zhipu": "openai_compatible",
    "kimi-coding": "openai_compatible",
    "kimi": "openai_compatible",
    "moonshot": "openai_compatible",
    "minimax": "openai_compatible",
    "minimax-cn": "openai_compatible",
    "deepseek": "openai_compatible",
    "ai-gateway": "openai_compatible",
    "vercel": "openai_compatible",
    "kilocode": "openai_compatible",
    "opencode-zen": "openai_compatible",
    "opencode-go": "openai_compatible",
    "huggingface": "openai_compatible",
    "alibaba": "openai_compatible",
}

