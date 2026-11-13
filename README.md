# Care Scheduling Agent

A patient-appointment scheduling agent that has to prove its own work: it never tells a patient
that something happened unless the (mock) EHR shows that it happened. The repository contains the
agent, a small in-process mock EHR with fault injection, and an evaluation harness with a
human-reviewed improvement loop and a regression gate.

**Final evaluation:** 6/6 in one complete live run, `20261113T123422Z` (`gemini-3.5-flash-lite`,
current checks, exit 0). Earlier runs and how they compare are in
[evals/evidence/README.md](evals/evidence/README.md).

## Where to start reading

- [Design note](docs/DESIGN.md): architecture, decisions, before/after results and limitations, on
  one page.
- [Incident answer](docs/INCIDENT.md): the written question, worked through with a real trace.
- [Evaluation](docs/EVALUATION.md): what each scenario tests, why grading reads the EHR, and what
  the results do and do not establish.
- [Improvement records](improvements/): IMP-001 to IMP-004, each with its evidence and limits.
- [Recorded evidence](evals/evidence/README.md): every real-model run and its provenance.
- [AI usage](docs/AI_USAGE.md): where Claude Code helped, where it was wrong, and where my judgment
  overrode it.
- Also: [architectural decisions](docs/design/DECISIONS.md) and a
  [manual real-model test](manual-tests/2026-11-12-reschedule.md).

Internal working files, kept for transparency but not needed to review the submission:
[pre-build analysis and plan](docs/internal/ANALYSIS.md) and
[progress log and time spent](docs/internal/PROGRESS.md).

## What needs a Gemini API key

Live agent conversations (`chat`) and live evaluation runs (`eval`) need a Gemini API key in
`LLM_API_KEY`. Without one, both commands stop with a configuration error (exit codes 1 and 2).

Without a key you can still run the full test suite (`python -m pytest`), in which a scripted model
drives the real agent, tools, EHR, fault injection, grading and regression gate with no network.
You can also read the recorded results: one sanitised summary per real run in
`evals/evidence/*.json`, indexed in [evals/evidence/README.md](evals/evidence/README.md).

Re-grading saved traces is not a supported command. Full traces go to the git-ignored `runs/`
folder and stay on the machine that ran them; the offline regrades mentioned in the docs were
one-off review scripts, not part of the tool.

## Setup

Python 3.12 or newer is required (developed on 3.14.10). Commands below are for Windows CMD; on
macOS or Linux use `source .venv/bin/activate` and `export`.

```bat
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -e ".[dev]"
```

Configuration is read directly from environment variables, never from files;
[.env.example](.env.example) lists the names. Never commit a real key.

```bat
set LLM_API_KEY=<your Gemini API key>
set LLM_MODEL=gemini-3.5-flash-lite
```

The recorded evidence used `gemini-3.5-flash-lite`; the default model is `gemini-3.1-flash-lite`.
Other optional settings: `LLM_PROVIDER` (only `gemini`), `LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS`
(default 30) and `LLM_TEMPERATURE` (default 0). Run every command from the repository root.

## Run the agent

```bat
python -m care_agent chat --phone +15550100001
```

Each run is a fresh simulated call against a new demo EHR, deleted when the call ends. Demo
patients: Maria Garcia (date of birth 1985-03-14, phone +15550100001, has a check-up booked) and
her husband Luis Garcia (1983-07-02, phone +15550100002). Type `quit` to hang up.

## Run the evaluation

```bat
python -m care_agent eval --record-evidence
```

This runs the six scenarios (one per assignment failure pattern, plus a cancellation that never
commits) against real Gemini, grades them from the EHR state, saves traces and failure reports to
`runs/`, and writes a sanitised evidence summary to `evals/evidence/`. Plain
`python -m care_agent eval` does the same without the evidence file.

The exit code is 0 when nothing regressed, 1 when a scenario that passed in `evals/baseline.json`
now fails, and 2 when the run could not complete (a missing key, or a model API error such as a
free-tier 429 that persists after the built-in backoff). A full run makes roughly 30–60 model
calls spaced at least 4 seconds apart, so it takes a few minutes. If the quota still runs out,
re-run single scenarios, for example `python -m care_agent eval --scenario E3`.

To rebuild the regression baseline from one complete run under the current checks:

```bat
python -m care_agent eval --rebuild-baseline --record-evidence
```

It replaces `evals/baseline.json` only if all six scenarios ran without an API error and none
regressed. The regression baseline, the historical pre-improvement score and the final score are
different things; see
[Baseline, historical score and final score](docs/EVALUATION.md#baseline-historical-score-and-final-score).

## Development

```bat
python -m pytest
python -m ruff check .
python -m ruff format --check .
```
