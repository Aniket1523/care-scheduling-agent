"""M0 smoke tests: the package imports and the CLI skeleton behaves as specified."""

import subprocess
import sys
from importlib.metadata import version

import pytest

import care_agent
from care_agent.cli import EXIT_NOT_IMPLEMENTED, main


def test_installed_metadata_version_matches_package_version():
    # pyproject.toml reads the version from care_agent.__version__; the installed
    # distribution must report the same value.
    assert version("care-scheduling-agent") == care_agent.__version__


def test_module_help_runs_and_lists_both_subcommands():
    # Runs the real `python -m care_agent` entry point in a fresh interpreter.
    result = subprocess.run(
        [sys.executable, "-m", "care_agent", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "chat" in result.stdout
    assert "eval" in result.stdout


def test_module_eval_exits_not_implemented_in_a_real_process():
    # Exercises the real entry point (__main__ -> sys.exit(main())), so the exit
    # code the shell sees is tested, not just main()'s return value.
    result = subprocess.run(
        [sys.executable, "-m", "care_agent", "eval"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == EXIT_NOT_IMPLEMENTED == 2
    assert "'eval' is not implemented yet" in result.stderr


def test_chat_placeholder_exits_not_implemented(capsys):
    assert main(["chat", "--phone", "+15550100001"]) == EXIT_NOT_IMPLEMENTED
    assert "'chat' is not implemented yet" in capsys.readouterr().err


def test_eval_placeholder_exits_not_implemented(capsys):
    assert main(["eval"]) == EXIT_NOT_IMPLEMENTED
    assert "'eval' is not implemented yet" in capsys.readouterr().err


def test_chat_requires_phone():
    with pytest.raises(SystemExit) as exc_info:
        main(["chat"])
    assert exc_info.value.code == 2


def test_missing_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2
