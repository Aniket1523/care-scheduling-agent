# Care Scheduling Agent

A patient-appointment scheduling agent that **proves its own work**: it never tells a patient that
something happened unless the (mock) EHR shows that it happened. The repository contains the agent, a
small in-process mock EHR with fault injection, and an evaluation harness with an improvement loop and a
regression gate.

> Status: complete. All six evaluation scenarios passed with real Gemini on the final code. The
> final verification was split across three runs because of free-tier rate limits; see
> [docs/DESIGN.md](docs/DESIGN.md) and [evals/evidence/README.md](evals/evidence/README.md).

## What needs a Gemini API key

**Live agent conversations (`chat`) and live evaluation runs (`eval`) need a Gemini API key**
(`LLM_API_KEY`). Without it, both commands stop with a configuration error (exit 1 and 2).

Without a key you can still:

- run the full test suite (`python -m pytest`): a scripted model drives the real agent, tools, EHR,
  fault injection, grading and regression gate, with no network;
- read the recorded results: `evals/evidence/*.json` (one sanitised summary per real run) and the
  index in [evals/evidence/README.md](evals/evidence/README.md);
- read the improvement records in [improvements/](improvements/).

Re-grading saved traces is **not** supported as a command: full traces are written to the
git-ignored `runs/` folder and stay on the machine that ran them. The earlier offline regrades
mentioned in the docs were one-off review scripts, not part of the tool.

Reviewer quick start: [design note](docs/DESIGN.md), [incident answer](docs/INCIDENT.md),
[evaluation](docs/EVALUATION.md), [evidence](evals/evidence/README.md),
[improvements](improvements/), [AI usage](docs/AI_USAGE.md).

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

The recorded evaluation evidence used `gemini-3.5-flash-lite`; to reproduce it:

```bat
set LLM_MODEL=gemini-3.5-flash-lite
```

Optional: `LLM_MODEL` (default `gemini-3.1-flash-lite`), `LLM_PROVIDER` (only `gemini`),
`LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS` (default 30), `LLM_TEMPERATURE` (default 0).
Tests never call the API and need no key.

Run every command below from the repository root, in a CMD window where
`.venv\Scripts\activate.bat` has been run and `LLM_API_KEY` is set.

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
Exit codes: 0 no regression, 1 regression, 2 could not run (missing key, or a model API error
such as a free-tier 429 that persists after the built-in backoff). A full run makes roughly 30-60
model calls, spaced at least 4 seconds apart, so it takes a few minutes. If the quota is still hit,
re-run single scenarios with `python -m care_agent eval --scenario E3`.

Full evaluation (all six scenarios, regression gate, plus a committed evidence summary):

```bat
python -m care_agent eval --record-evidence
```

To rebuild the regression baseline from one complete run under the current checks:

```bat
python -m care_agent eval --rebuild-baseline --record-evidence
```

It replaces `evals/baseline.json` only if all six scenarios ran without an API error and none
regressed. The regression baseline, the historical pre-improvement score and the final score are
different things: see [Three different scores](docs/EVALUATION.md#three-different-scores).
See [docs/EVALUATION.md](docs/EVALUATION.md) for options, outputs and the improvement loop.

## Development

```bat
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

## Documentation

- [Design note](docs/DESIGN.md) (one page: choices, loop, before/after, limitations)
- [Incident answer](docs/INCIDENT.md) (the written question)
- [Evaluation and improvement loop](docs/EVALUATION.md); [recorded evidence](evals/evidence/README.md);
  [improvement records](improvements/)
- [AI usage log](docs/AI_USAGE.md)
- [Architectural decisions](docs/design/DECISIONS.md)
- [Manual real-model test](manual-tests/2026-11-12-reschedule.md)

Internal working files (kept for transparency, not needed to review the submission):
[pre-build analysis and plan](docs/internal/ANALYSIS.md),
[progress log and time spent](docs/internal/PROGRESS.md).
