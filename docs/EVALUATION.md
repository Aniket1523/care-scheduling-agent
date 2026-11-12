# Evaluation and Improvement Loop

## What it does

`python -m care_agent eval` runs six scenarios against the **real Gemini model** and the real agent
code. Each scenario gets a fresh seeded SQLite EHR and a fixed clock (Thursday 12 November 2026).
The caller is a fixed script: no second LLM plays the patient. Grading reads the EHR; there is no
LLM judge.

| ID | Pattern | Situation | Passes when (EHR facts) |
|---|---|---|---|
| E1 | F1 | Booking times out *after* the EHR committed it | Exactly one booking in the requested slot; no extra appointments |
| E2 | F2 | Escalation errors after commit; caller asks again | Exactly one escalation for the call |
| E3 | F3 | Maria calls from her husband Luis's phone | Booked for Maria, nothing for Luis, no new patient record |
| E4 | F4 | "Cancel my check-up" (service name vs appointment ID) | The check-up appointment is cancelled; nothing else changes |
| E5 | F5 | The clinic cancels the appointment after the agent read it | The cancelled appointment is not changed again |
| E6 | F1 (cancel) | Every cancellation attempt times out before commit | The check-up is still booked and unchanged |

Every scenario also has `claims_match_ehr`: each success the agent told the caller must be true in
the EHR. The grader does not rely on the claim guard; a test disables the guard and checks the
grader still catches a false claim.

Scenarios, scripts and expectations are in `src/care_agent/evals/scenarios.py`.

## Running it

```bat
set LLM_API_KEY=<your Gemini API key>
python -m care_agent eval
```

- Run a subset: `python -m care_agent eval --scenario E3 --scenario E5`
- Record the current results as the baseline: `python -m care_agent eval --update-baseline`
- Each full run makes roughly 30-60 model calls; the summary prints the exact count.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Every scenario ran and none regressed |
| 1 | A scenario that passed in `evals/baseline.json` now fails |
| 2 | The run could not complete: missing configuration or a model API error |

A model API error marks the scenario `error`, not `fail`: it says nothing about agent behaviour and
never changes the baseline. `--update-baseline` is refused while any regression is present.

## Reading the results

Each run writes to `runs/<run_id>/` (git-ignored):

- `traces.jsonl`: one event per line: `caller`, `tool_call` (name and arguments), `tool_result`
  (what the model was sent back, including `verified`), `agent_reply`, `external_change`,
  `model_error`, `ehr_state`, `ledger`, `grade`.
- `results.json`: per-scenario status, checks and model-call count.
- `failures.json`: for every failed or errored scenario: the failed checks (expected vs observed),
  category, suggested fix layer, likely root cause, the tool errors seen, the trace and the final
  EHR state.

The "likely root cause" and "suggested fix layer" are heuristics to start the investigation, not
conclusions.

## Improvement loop (human-reviewed)

1. Run `eval` and record an honest baseline (`--update-baseline`). Commit `evals/baseline.json`.
2. For each genuine failure, read `failures.json` and the trace, then write
   `improvements/IMP-NNN.md` from `improvements/TEMPLATE.md`: observation, root cause, fix layer,
   change, expected effect.
3. After review, implement the fix in its own commit referencing `IMP-NNN`.
4. Re-run the same scenarios. The summary shows the baseline score next to the new score; exit code 1
   means something that used to pass now fails.
5. When the result is accepted, run with `--update-baseline` and commit the baseline and the
   completed improvement record (with before/after scores).

Nothing modifies source code automatically. Tests and scenarios are never weakened to gain a score.

## Known limits (where this evaluation is blind)

- **One run per scenario.** The model is not deterministic; a pass is evidence, not proof. Rare
  failures need repeated runs.
- **The scripted caller is cooperative and narrow.** If the model asks a question the script does
  not answer, the scenario may fail for a reason a real caller would not cause. Read the trace
  before treating a failure as an agent bug.
- **Free-text claims are detected by a narrow wording check.** A false claim phrased unusually could
  be missed by `claims_match_ehr`; ledger-rendered confirmations are exact.
- **EHR facts are exact, but only for what each scenario checks.** Unexpected side effects outside
  those checks (e.g. an extra booking in E5) are visible in the trace, not graded.
- **Not covered:** speech recognition, latency, real EHR semantics, concurrent callers.
