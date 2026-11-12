"""Interactive text session: one simulated phone call against a fresh demo EHR."""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from care_agent.agent.gemini import GeminiClient
from care_agent.agent.loop import Agent, ModelClient
from care_agent.agent.prompt import build_system_prompt
from care_agent.agent.state import ConversationState
from care_agent.agent.tools import TOOL_DECLARATIONS, ToolRunner, new_call_id
from care_agent.config import ConfigError, LLMSettings
from care_agent.ehr.db import connect, init_db
from care_agent.ehr.models import Phone
from care_agent.ehr.seed import seed_demo_data
from care_agent.ehr.service import normalize_phone

EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_USAGE = 2

QUIT_WORDS = {"quit", "exit", "bye"}

BANNER = """\
Care scheduling agent - simulated call from {phone}. Type 'quit' to hang up.
Demo patients: Maria Garcia (DOB 1985-03-14, phone +15550100001, has a check-up booked)
               Luis Garcia  (DOB 1983-07-02, phone +15550100002)"""


def run_chat(
    phone: str,
    *,
    client: ModelClient | None = None,
    environ: Mapping[str, str] | None = None,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    try:
        caller_phone = TypeAdapter(Phone).validate_python(normalize_phone(phone))
    except ValidationError:
        print(f"Invalid --phone value: {phone!r} (expected e.g. +15550100001)", file=sys.stderr)
        return EXIT_USAGE

    if client is None:
        try:
            settings = LLMSettings.from_env(environ)
            client = GeminiClient(settings, build_system_prompt(clock().date()), TOOL_DECLARATIONS)
        except ConfigError as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            return EXIT_CONFIG_ERROR

    with tempfile.TemporaryDirectory(prefix="care_agent_") as tmp:
        conn = connect(Path(tmp) / "demo_ehr.sqlite3")
        try:
            init_db(conn)
            seed_demo_data(conn, clock())
            state = ConversationState(call_id=new_call_id(), caller_phone=caller_phone)
            agent = Agent(client, ToolRunner(conn, state, clock), state)
            write(BANNER.format(phone=caller_phone))
            while True:
                try:
                    text = read("You: ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not text:
                    continue
                if text.lower() in QUIT_WORDS:
                    break
                agent.last_model_error = None
                reply = agent.respond(text)
                if agent.last_model_error is not None:
                    error = agent.last_model_error
                    print(f"[model error: {type(error).__name__}: {error}]"[:400], file=sys.stderr)
                write(f"Agent: {reply}")
        finally:
            conn.close()
    write("Call ended.")
    return EXIT_OK
