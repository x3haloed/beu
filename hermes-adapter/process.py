from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

from ._shared import DEFAULT_BEU_BINARY, DEFAULT_NAMESPACE, HERMES_HOME, logger


class BeuProcess:
    """Manages the BeU binary subprocess and communication."""

    _instance: Optional["BeuProcess"] = None
    _lock = threading.Lock()

    def __init__(self, binary_path: Optional[str] = None):
        self.binary_path = self._resolve_binary_path(binary_path)
        self.process: Optional[subprocess.Popen] = None
        self._ensure_binary()

    def _resolve_binary_path(self, binary_path: Optional[str]) -> str:
        if binary_path:
            return binary_path
        env_binary = os.environ.get("BEU_BINARY_PATH")
        if env_binary and Path(env_binary).is_absolute():
            return env_binary
        hermes_binary = HERMES_HOME / "plugins" / "hermes-adapter" / "beu"
        if hermes_binary.is_absolute():
            return str(hermes_binary)
        return DEFAULT_BEU_BINARY

    def _ensure_binary(self) -> None:
        path = Path(self.binary_path)
        if path.exists() and os.access(path, os.X_OK):
            return
        try:
            result = subprocess.run(
                ["which", self.binary_path], capture_output=True, text=True, check=False
            )
            if result.returncode == 0 and result.stdout.strip():
                self.binary_path = result.stdout.strip()
                return
        except Exception:
            pass
        raise RuntimeError(f"BeU binary not found at: {self.binary_path}")

    def call(self, command: str, payload: dict, namespace: str = DEFAULT_NAMESPACE) -> dict:
        request = {
            "version": "1.0.0",
            "command": command,
            "id": f"{command}-{os.urandom(4).hex()}",
            "namespace": namespace,
            "payload": payload,
        }
        try:
            proc = subprocess.run(
                [self.binary_path],
                input=json.dumps(request) + "\n",
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if proc.returncode != 0:
                logger.error("BeU process error: %s", proc.stderr)
                return {"ok": False, "error": proc.stderr or "Process exited with non-zero status"}
            return json.loads(proc.stdout.strip())
        except subprocess.TimeoutExpired:
            logger.error("BeU command timed out")
            return {"ok": False, "error": "Command timed out"}
        except json.JSONDecodeError as e:
            logger.error("Failed to parse BeU response: %s", e)
            return {"ok": False, "error": f"Invalid JSON response: {e}"}
        except Exception as e:
            logger.error("BeU command failed: %s", e)
            return {"ok": False, "error": str(e)}

    def distill(self, payload: dict, namespace: str = DEFAULT_NAMESPACE) -> dict:
        response = self.call("distill", payload, namespace)
        if response.get("ok"):
            return response.get("data", {})
        logger.warning("Distill failed: %s", response.get("error"))
        return {}

    def distill_tick(self, payload: dict, namespace: str = DEFAULT_NAMESPACE) -> dict:
        response = self.call("distill_tick", payload, namespace)
        if response.get("ok"):
            return response.get("data", {})
        logger.warning("Distill tick failed: %s", response.get("error"))
        return {}

    def distill_reset(self, payload: dict, namespace: str = DEFAULT_NAMESPACE) -> dict:
        response = self.call("distill_reset", payload, namespace)
        if response.get("ok"):
            return response.get("data", {})
        logger.warning("Distill reset failed: %s", response.get("error"))
        return {}

    def recall(self, query: str, namespace: str = DEFAULT_NAMESPACE, limit: int = 6) -> dict:
        response = self.call("recall", {"query": query, "limit": limit}, namespace)
        if response.get("ok"):
            return response.get("data", {})
        logger.warning("Recall failed: %s", response.get("error"))
        return {}


def get_beu() -> BeuProcess:
    with BeuProcess._lock:
        if BeuProcess._instance is None:
            BeuProcess._instance = BeuProcess()
        return BeuProcess._instance
