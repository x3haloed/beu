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


def _install_hermes_config_module(*, config: dict):
    pkg = types.ModuleType("hermes_cli")
    pkg.__path__ = []  # type: ignore[attr-defined]
    config_mod = types.ModuleType("hermes_cli.config")
    config_mod.load_config = lambda: config
    return {"hermes_cli": pkg, "hermes_cli.config": config_mod}


class TestBeUHookInvocation(unittest.TestCase):
    def test_llm_hooks_accept_hermes_keyword_invocation(self):
        with patch.object(beu, "_index_entry") as index_entry, patch.object(
            beu, "get_beu"
        ) as get_beu:
            get_beu.return_value.recall.return_value = {}
            pre_result = beu.pre_llm_call_hook(
                session_id="s1",
                user_message="hello",
                conversation_history=[],
                model="test-model",
                platform="cli",
            )
            post_result = beu.post_llm_call_hook(
                session_id="s1",
                assistant_response="world",
                user_message="hello",
                conversation_history=[],
                model="test-model",
                platform="cli",
            )

        self.assertIsNone(pre_result)
        self.assertIsNone(post_result)
        self.assertEqual(index_entry.call_count, 2)
        get_beu.return_value.recall.assert_called_once()

    def test_llm_hooks_ignore_empty_turns_without_error(self):
        with patch.object(beu, "_index_entry") as index_entry:
            pre_result = beu.pre_llm_call_hook(session_id="s1", user_message="")
            post_result = beu.post_llm_call_hook(session_id="s1", assistant_response="")

        self.assertIsNone(pre_result)
        self.assertIsNone(post_result)
        index_entry.assert_not_called()

    def test_pre_llm_injects_ledger_recall_block_when_hits_exist(self):
        with TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            binary_path = Path(__file__).resolve().parents[2] / "target" / "debug" / "beu"
            self.assertTrue(binary_path.exists(), f"missing built binary: {binary_path}")

            with patch.object(beu.BeuProcess, "_instance", None), patch.dict(
                os.environ,
                {
                    "BEU_BINARY_PATH": str(binary_path),
                    "BEU_STATE_DIR": str(state_dir),
                },
                clear=False,
            ), patch.object(beu, "_index_entry"):
                beu.get_beu().call(
                    "index",
                    {
                        "entries": [
                            {
                                "entry_id": "entry-1",
                                "source_type": "user_turn",
                                "source_id": "turn-1",
                                "content": "User prefers detailed explanations",
                                "metadata": {
                                    "thread_id": "s1",
                                    "turn_id": "turn-1",
                                },
                            }
                        ]
                    },
                    namespace="s1",
                )
                recall = beu.get_beu().call(
                    "recall",
                    {"query": "detailed", "limit": 5},
                    namespace="s1",
                )
                block = recall["data"]["ledger_recall_block"]
                hook_result = beu.pre_llm_call_hook(
                    session_id="s1",
                    user_message="",
                    system_prompt="detailed",
                )
                self.assertIsInstance(block, str)
                self.assertEqual(recall["data"]["hits"][0]["citation"], "entry-1")
                expected_block = (
                    "<ledger_recall>\n"
                    "Information from prior runtime history:\n"
                    f"- [entry-1] User prefers detailed explanations ↳ For more, call: `{{ \"type\": \"function_call\", \"name\": \"ledger_get\", \"arguments\": \"{{\\\"namespace\\\":\\\"s1\\\",\\\"entry_id\\\":\\\"{recall['data']['hits'][0]['entry_id']}\\\"}}\" }}`\n"
                    "</ledger_recall>"
                )
                self.assertEqual(block, expected_block)
                self.assertEqual(hook_result, expected_block)


class TestBeUEmbeddingResolution(unittest.TestCase):
    def test_named_distill_block_takes_priority_over_model(self):
        with TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "beu.yaml"
            cfg_path.write_text(
                """distill:
  provider: openrouter
  model: anthropic/claude-sonnet-4
model:
  provider: anthropic
  model: claude-3-5-sonnet-latest
""",
                encoding="utf-8",
            )

            modules = _install_runtime_provider_module(
                requested_provider="openai-codex",
                runtime={"provider": "openrouter", "model": "should-not-be-used"},
            )
            modules.update(
                _install_hermes_config_module(
                    config={
                        "distill": {
                            "provider": "openrouter",
                            "model": "anthropic/claude-sonnet-4",
                        },
                        "model": {
                            "provider": "anthropic",
                            "model": "claude-3-5-sonnet-latest",
                        },
                    }
                )
            )
            with patch.dict(sys.modules, modules), patch.dict(
                os.environ, {"BEU_CONFIG_PATH": str(cfg_path)}, clear=False
            ):
                result = beu._candidate_distill_payloads()

        self.assertGreaterEqual(len(result), 1)
        self.assertEqual(
            result[0],
            {"provider": "openai_compatible", "model": "anthropic/claude-sonnet-4"},
        )

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
