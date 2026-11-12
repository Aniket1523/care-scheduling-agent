# Care Scheduling Agent

A patient-appointment scheduling agent that **proves its own work**: it never tells a patient that
something happened unless the (mock) EHR shows that it happened. The repository contains the agent, a
small in-process mock EHR with fault injection, and an evaluation harness with an improvement loop and a
regression gate.

> Status: **M0 – project skeleton.** The `chat` and `eval` commands are placeholders and exit with
> code 2 until milestones M3 and M4. See [docs/PROGRESS.md](docs/PROGRESS.md).

## Requirements

- Python 3.12 or newer (developed on 3.14.10)
- Windows CMD commands are shown below; on macOS/Linux use `source .venv/bin/activate` and `export`.

## Setup

```bat
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -e ".[dev]"
```

## Configuration

The agent reads its LLM configuration directly from environment variables. Nothing is read from files;
[.env.example](.env.example) lists the names. Never commit a real key.

```bat
set LLM_PROVIDER=<provider>
set LLM_MODEL=<model>
set LLM_API_KEY=<your key>
```

Optional: `LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS` (default 30), `LLM_TEMPERATURE` (default 0).

## Run the agent

```bat
python -m care_agent chat --phone +15550100001
```

## Run the evaluation loop

```bat
python -m care_agent eval
```

## Development

```bat
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

## Documentation

- [Requirements analysis and architecture](docs/design/ANALYSIS.md)
- [Architectural decisions](docs/design/DECISIONS.md)
- [Progress and time tracking](docs/PROGRESS.md)
- [AI usage log](docs/AI_USAGE.md)
