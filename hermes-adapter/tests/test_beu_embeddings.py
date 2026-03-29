from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "__init__.py"
SPEC = importlib.util.spec_from_file_location("beu_adapter_under_test", MODULE_PATH)
beu = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(beu)


def _install_runtime_provider_module(*, requested_provider: str, runtime: dict):
    pkg = types.ModuleType("hermes_cli")
    pkg.__path__ = []  # type: ignore[attr-defined]
    runtime_mod = types.ModuleType("hermes_cli.runtime_provider")
    runtime_mod.resolve_requested_provider = lambda: requested_provider
    runtime_mod.resolve_runtime_provider = lambda requested=None: runtime
    return {"hermes_cli": pkg, "hermes_cli.runtime_provider": runtime_mod}


class TestBeUEmbeddingResolution(unittest.TestCase):
    def test_beu_local_embeddings_config_wins(self):
        with TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "beu.yaml"
            cfg_path.write_text(
                """embeddings:
  provider: google
  model: text-embedding-004
""",
                encoding="utf-8",
            )

            modules = _install_runtime_provider_module(
                requested_provider="openai-codex",
                runtime={"provider": "openrouter", "model": "should-not-be-used"},
            )
            with patch.dict(sys.modules, modules), patch.dict(
                os.environ, {"BEU_CONFIG_PATH": str(cfg_path)}, clear=False
            ):
                result = beu._resolve_embedding_provider(namespace="default", kwargs={})

        self.assertEqual(
            result,
            {"provider": "google", "model": "text-embedding-004"},
        )

    def test_falls_back_to_hermes_runtime_provider_when_no_local_config(self):
        modules = _install_runtime_provider_module(
            requested_provider="custom:beu-embeddings",
            runtime={
                "provider": "google",
                "model": "text-embedding-004",
                "base_url": "",
                "api_key": "",
            },
        )
        with patch.dict(sys.modules, modules), patch.object(
            beu, "_collect_beu_embedding_settings", return_value={}
        ):
            result = beu._resolve_embedding_provider(namespace="default", kwargs={})

        self.assertEqual(
            result,
            {"provider": "google", "model": "text-embedding-004"},
        )

    def test_env_override_can_define_custom_endpoint(self):
        with TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "beu.yaml"
            cfg_path.write_text("""embeddings: {}
""", encoding="utf-8")

            modules = _install_runtime_provider_module(
                requested_provider="openai-codex",
                runtime={"provider": "openrouter", "model": "fallback-model"},
            )
            env = {
                "BEU_CONFIG_PATH": str(cfg_path),
                "BEU_EMBEDDINGS_PROVIDER": "custom",
                "BEU_EMBEDDINGS_BASE_URL": "https://embeddings.example/v1",
                "BEU_EMBEDDINGS_API_KEY": "secret",
                "BEU_EMBEDDINGS_MODEL": "text-embedding-3-small",
            }
            with patch.dict(sys.modules, modules), patch.dict(os.environ, env, clear=False):
                result = beu._resolve_embedding_provider(namespace="default", kwargs={})

        self.assertEqual(
            result,
            {
                "provider": "custom",
                "model": "text-embedding-3-small",
                "base_url": "https://embeddings.example/v1",
                "api_key": "secret",
            },
        )


if __name__ == "__main__":
    unittest.main()
