# Care Scheduling Agent

A patient-appointment scheduling agent that **proves its own work**: it never tells a patient that
something happened unless the (mock) EHR shows that it happened. The repository contains the agent, a
small in-process mock EHR with fault injection, and an evaluation harness with an improvement loop and a
regression gate.

> Status: the mock EHR, the scheduling agent and the evaluation harness work. See
> [docs/PROGRESS.md](docs/PROGRESS.md).

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

The agent uses Google Gemini and reads its configuration directly from environment variables.
Nothing is read from files; [.env.example](.env.example) lists the names. Never commit a real key.

```bat
set LLM_API_KEY=<your Gemini API key>
```

Optional: `LLM_MODEL` (default `gemini-3.1-flash-lite`), `LLM_PROVIDER` (only `gemini`),
`LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS` (default 30), `LLM_TEMPERATURE` (default 0).
Tests never call the API and need no key.

## Run the agent

```bat
python -m care_agent chat --phone +15550100001
```

Each run is a fresh simulated call against a new demo EHR (deleted when the call ends). Demo patients:
Maria Garcia (DOB 1985-03-14, phone +15550100001, has a check-up booked) and her husband Luis Garcia
(DOB 1983-07-02, phone +15550100002). Type `quit` to hang up.

## Run the evaluation loop

```bat
python -m care_agent eval
```

Runs six scenarios (one per assignment failure pattern, plus a cancellation that never commits)
against the real Gemini model, grades them from the EHR state, saves traces and failure reports to
`runs/`, and exits with code 1 if a scenario that passed in `evals/baseline.json` now fails.
See [docs/EVALUATION.md](docs/EVALUATION.md) for options, outputs and the improvement loop.

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
