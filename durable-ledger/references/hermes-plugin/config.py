from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from ._shared import DEFAULT_NAMESPACE_STRATEGY, HERMES_HOME, logger


DURABLE_LEDGER_CONFIG_ENV = "DURABLE_LEDGER_CONFIG_PATH"
DEFAULT_CONFIG_FILENAMES = ("durable-ledger.yaml", "durable-ledger.yml")
STORAGE_ROOT_ENV = "DURABLE_LEDGER_STORAGE_ROOT"
NAMESPACE_STRATEGY_ENV = "DURABLE_LEDGER_NAMESPACE_STRATEGY"


@dataclass(frozen=True)
class DurableLedgerSettings:
    storage_root: Path
    namespace_strategy: tuple[str, ...]


def _candidate_paths() -> list[Path]:
    candidate_paths: list[Path] = []
    env_path = os.environ.get(DURABLE_LEDGER_CONFIG_ENV, "").strip()
    if env_path:
        candidate_paths.append(Path(env_path).expanduser())
    adapter_dir = Path(__file__).resolve().parent
    candidate_paths.extend(adapter_dir / name for name in DEFAULT_CONFIG_FILENAMES)
    return candidate_paths


def _resolve_config_path(prefer_existing: bool = True) -> Path:
    candidate_paths = _candidate_paths()
    if prefer_existing:
        for path in candidate_paths:
            if path.is_file():
                return path
    if candidate_paths:
        return candidate_paths[0]
    return Path(__file__).resolve().parent / DEFAULT_CONFIG_FILENAMES[0]


def _load_config_data() -> dict:
    path = _resolve_config_path(prefer_existing=True)
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("Failed to read durable-ledger config %s: %s", path, exc)
        return {}
    if isinstance(data, dict):
        return data
    logger.warning("Durable-ledger config %s must contain a mapping", path)
    return {}


def _parse_namespace_strategy(raw: str) -> tuple[str, ...]:
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    return tuple(parts) or tuple(DEFAULT_NAMESPACE_STRATEGY.split(","))


def load_settings() -> DurableLedgerSettings:
    config = _load_config_data()
    storage_root = (
        os.environ.get(STORAGE_ROOT_ENV, "").strip()
        or str(config.get("storage_root") or "").strip()
        or str(HERMES_HOME / "state" / "durable-ledger")
    )
    namespace_strategy = (
        os.environ.get(NAMESPACE_STRATEGY_ENV, "").strip()
        or str(config.get("namespace_strategy") or "").strip()
        or DEFAULT_NAMESPACE_STRATEGY
    )
    return DurableLedgerSettings(
        storage_root=Path(storage_root).expanduser(),
        namespace_strategy=_parse_namespace_strategy(namespace_strategy),
    )