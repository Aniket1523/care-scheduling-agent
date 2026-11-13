"""Rate-limit handling: pacing and backoff around model calls (no network)."""

from __future__ import annotations

import json

import pytest
from google.genai import errors, types

from care_agent.agent.gemini import RateLimitedClient, is_rate_limit
from care_agent.evals.suite import EXIT_INCOMPLETE, run_eval

CONTENT = types.Content(role="model", parts=[types.Part(text="hello")])


def rate_limit_error() -> errors.ClientError:
    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota"}}
    return errors.ClientError(429, body)


class FlakyModel:
    """Raises the given errors in order, then returns CONTENT."""

    def __init__(self, failures: list[Exception]) -> None:
        self.failures = list(failures)
        self.calls = 0

    def generate(self, contents):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return CONTENT


class AlwaysRateLimited:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, contents):
        self.calls += 1
        raise rate_limit_error()


def wrap(inner, sleeps: list[float], **kwargs) -> RateLimitedClient:
    return RateLimitedClient(inner, sleep=sleeps.append, rand=lambda: 0.5, **kwargs)


def test_rate_limit_is_recognised_and_other_errors_are_not():
    assert is_rate_limit(rate_limit_error())
    assert not is_rate_limit(errors.ClientError(400, {"error": {"status": "INVALID_ARGUMENT"}}))
    assert not is_rate_limit(RuntimeError("boom"))


def test_transient_rate_limit_is_retried_with_exponential_backoff_and_jitter():
    sleeps: list[float] = []
    inner = FlakyModel([rate_limit_error(), rate_limit_error()])
    client = wrap(inner, sleeps)
    assert client.generate([]) is CONTENT
    assert inner.calls == 3
    assert sleeps == [5.5, 10.5]  # 5 * 2**n, plus 1.0 * 0.5 of jitter


def test_persistent_rate_limit_is_raised_after_the_last_attempt():
    sleeps: list[float] = []
    inner = AlwaysRateLimited()
    client = wrap(inner, sleeps, max_attempts=5, max_delay=30.0)
    with pytest.raises(errors.ClientError):
        client.generate([])
    assert inner.calls == 5
    assert sleeps == [5.5, 10.5, 20.5, 30.5]  # capped at max_delay; no sleep after the last


def test_other_errors_are_not_retried():
    sleeps: list[float] = []
    inner = FlakyModel([RuntimeError("bad request")])
    with pytest.raises(RuntimeError):
        wrap(inner, sleeps).generate([])
    assert inner.calls == 1 and sleeps == []


def test_calls_are_spaced_by_the_minimum_interval():
    sleeps: list[float] = []
    times = iter([100.0, 101.0, 110.0])
    client = wrap(FlakyModel([]), sleeps, min_interval=4.0, clock=lambda: next(times))
    client.generate([])  # t=100: first call, no wait
    client.generate([])  # t=101: 1 s after the last call, so wait 3 s
    client.generate([])  # t=110: already 6 s later, no wait
    assert sleeps == [3.0]


def test_persistent_rate_limit_in_an_eval_is_an_error_not_a_regression(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"E1": "pass"}))
    output: list[str] = []
    code = run_eval(
        ["E1"],
        update_baseline=True,
        client_factory=lambda scenario: wrap(AlwaysRateLimited(), []),
        baseline_path=baseline,
        runs_dir=tmp_path / "runs",
        write=output.append,
    )
    assert code == EXIT_INCOMPLETE  # 2: could not run, not 1: regression
    assert any("ERROR in E1: ClientError: 429 RESOURCE_EXHAUSTED" in line for line in output)
    assert not any("REGRESSION" in line for line in output)
    assert json.loads(baseline.read_text()) == {"E1": "pass"}
