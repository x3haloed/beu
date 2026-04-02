from __future__ import annotations

import logging
import os
from pathlib import Path


logger = logging.getLogger("durable_ledger.hermes")

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
DEFAULT_NAMESPACE = "default"
DEFAULT_NAMESPACE_STRATEGY = "session_key,session_id,task_id,default"