"""Temporary, opt-in diagnostics for tool calls (CARE_AGENT_DEBUG_TOOLS=1).

Writes one line per event to stderr. It logs tool names, tool arguments and
tool results only - never the API key, the system prompt or the conversation
history. Off unless the variable is exactly "1"; checked on every call so it
can be switched without restarting anything else.
"""

from __future__ import annotations

import json
import os
import sys

ENV_FLAG = "CARE_AGENT_DEBUG_TOOLS"


def enabled() -> bool:
    return os.environ.get(ENV_FLAG) == "1"


def log(event: str, **fields: object) -> None:
    if not enabled():
        return
    details = " ".join(f"{k}={json.dumps(v, default=str)}" for k, v in fields.items())
    print(f"[debug-tools] {event} {details}".rstrip(), file=sys.stderr, flush=True)
