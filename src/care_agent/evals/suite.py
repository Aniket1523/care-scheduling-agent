"""``python -m care_agent eval``: run the scenarios, save traces, gate on regressions.

Outputs, under ``runs/<run_id>/`` (git-ignored):

* ``traces.jsonl``  - one JSON event per line: caller turns, tool calls and
  results, agent replies, final EHR state, grade.
* ``results.json``  - per-scenario status, checks and model-call counts.
* ``failures.json`` - a structured report for every failed or errored scenario.

The baseline (``evals/baseline.json``, committed) records which scenarios
passed. Exit codes:

* 0 - no regression and every scenario ran;
* 1 - a scenario that passed in the baseline now fails;
* 2 - the run could not complete (missing configuration, or a model API error).

The baseline changes only with ``--update-baseline``, which is refused while a
regression is present, so a previously passing scenario cannot silently drop.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from care_agent.agent.loop import ModelClient
from care_agent.evals.runner import ScenarioResult, failure_report, run_scenario
from care_agent.evals.scenarios import SCENARIOS, SCENARIOS_BY_ID, Scenario

EXIT_OK = 0
EXIT_REGRESSION = 1
EXIT_INCOMPLETE = 2

DEFAULT_BASELINE = Path("evals/baseline.json")
DEFAULT_RUNS_DIR = Path("runs")


def load_baseline(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def regressions(baseline: dict[str, str], results: Sequence[ScenarioResult]) -> list[str]:
    """Scenarios that passed in the baseline and now fail."""
    return [
        r.scenario_id
        for r in results
        if baseline.get(r.scenario_id) == "pass" and r.status == "fail"
    ]


def run_eval(
    scenario_ids: Sequence[str] | None = None,
    *,
    update_baseline: bool = False,
    client_factory: Callable[[Scenario], ModelClient] | None = None,
    baseline_path: Path = DEFAULT_BASELINE,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    write: Callable[[str], None] = print,
) -> int:
    unknown = [s for s in scenario_ids or [] if s not in SCENARIOS_BY_ID]
    if unknown:
        print(f"Unknown scenario(s): {', '.join(unknown)}", file=sys.stderr)
        return EXIT_INCOMPLETE
    scenarios = [SCENARIOS_BY_ID[s] for s in scenario_ids] if scenario_ids else list(SCENARIOS)

    if client_factory is None:
        from care_agent.agent.gemini import GeminiClient
        from care_agent.agent.prompt import build_system_prompt
        from care_agent.agent.tools import TOOL_DECLARATIONS
        from care_agent.config import ConfigError, LLMSettings
        from care_agent.evals.scenarios import EVAL_NOW

        try:
            client = GeminiClient(
                LLMSettings.from_env(), build_system_prompt(EVAL_NOW.date()), TOOL_DECLARATIONS
            )
        except ConfigError as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            return EXIT_INCOMPLETE
        client_factory = lambda scenario: client  # noqa: E731 - one stateless client for all

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = runs_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for scenario in scenarios:
        write(f"Running {scenario.id} ({scenario.failure_pattern}): {scenario.title} ...")
        results.append(run_scenario(scenario, client_factory(scenario)))

    baseline = load_baseline(baseline_path)
    regressed = regressions(baseline, results)
    _write_outputs(out_dir, run_id, scenarios, results)
    _print_summary(write, scenarios, results, baseline, regressed, out_dir)

    if update_baseline:
        if regressed:
            write("Baseline NOT updated: fix the regression(s) first.")
        else:
            _update_baseline(baseline_path, baseline, results)
            write(f"Baseline updated: {baseline_path}")

    if regressed:
        return EXIT_REGRESSION
    if any(r.status == "error" for r in results):
        return EXIT_INCOMPLETE
    return EXIT_OK


def _update_baseline(
    path: Path, baseline: dict[str, str], results: Sequence[ScenarioResult]
) -> None:
    updated = dict(baseline)
    for result in results:
        if result.status in ("pass", "fail"):  # an errored run proves nothing either way
            updated[result.scenario_id] = result.status
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(updated.items())), indent=2) + "\n", encoding="utf-8")


def _write_outputs(
    out_dir: Path, run_id: str, scenarios: Sequence[Scenario], results: Sequence[ScenarioResult]
) -> None:
    with (out_dir / "traces.jsonl").open("w", encoding="utf-8") as trace:
        for result in results:
            for event in result.events:
                trace.write(
                    json.dumps(
                        {"run_id": run_id, "scenario_id": result.scenario_id, **event}, default=str
                    )
                    + "\n"
                )
            grade_event = {
                "run_id": run_id,
                "scenario_id": result.scenario_id,
                "event": "grade",
                "status": result.status,
                "checks": [_check_dict(c) for c in result.checks],
            }
            trace.write(json.dumps(grade_event) + "\n")

    summary: dict[str, Any] = {
        "run_id": run_id,
        "scenarios": [
            {
                "scenario_id": r.scenario_id,
                "status": r.status,
                "model_calls": r.model_calls,
                "error": r.error,
                "checks": [_check_dict(c) for c in r.checks],
            }
            for r in results
        ],
    }
    (out_dir / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    by_id = {s.id: s for s in scenarios}
    reports = [failure_report(by_id[r.scenario_id], r) for r in results if r.status != "pass"]
    (out_dir / "failures.json").write_text(
        json.dumps(reports, indent=2, default=str), encoding="utf-8"
    )


def _check_dict(check: Any) -> dict[str, Any]:
    return {
        "name": check.name,
        "passed": check.passed,
        "description": check.description,
        "detail": check.detail,
    }


def _print_summary(
    write: Callable[[str], None],
    scenarios: Sequence[Scenario],
    results: Sequence[ScenarioResult],
    baseline: dict[str, str],
    regressed: Sequence[str],
    out_dir: Path,
) -> None:
    by_id = {s.id: s for s in scenarios}
    write("")
    write(f"{'ID':4} {'Pattern':12} {'Baseline':9} {'Now':6} {'Calls':5}  Failed checks")
    for r in results:
        failed = ", ".join(c.name for c in r.failed_checks) or (
            "-" if r.status != "error" else "model error"
        )
        write(
            f"{r.scenario_id:4} {by_id[r.scenario_id].failure_pattern:12} "
            f"{baseline.get(r.scenario_id, 'n/a'):9} {r.status:6} {r.model_calls:5}  {failed}"
        )
    passed = sum(r.status == "pass" for r in results)
    before = sum(baseline.get(r.scenario_id) == "pass" for r in results)
    write("")
    write(f"Score: {passed}/{len(results)} passed (baseline: {before}/{len(results)})")
    write(f"Model calls: {sum(r.model_calls for r in results)}")
    if not baseline:
        write("No baseline yet: run again with --update-baseline to record one.")
    for scenario_id in regressed:
        write(f"REGRESSION: {scenario_id} passed in the baseline and now fails.")
    for r in results:
        if r.status == "error":
            write(f"ERROR in {r.scenario_id}: {r.error}")
    write(f"Traces and reports: {out_dir}")
