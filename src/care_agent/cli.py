"""Command-line interface.

Two subcommands, matching the two commands the README documents:

* ``chat`` - talk to the scheduling agent as a caller.
* ``eval`` - run the evaluation scenarios and the regression gate.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from care_agent import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="care_agent",
        description="Patient-appointment scheduling agent with a mock EHR and evaluation harness.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subcommands = parser.add_subparsers(dest="command", metavar="COMMAND")
    subcommands.required = True

    chat = subcommands.add_parser("chat", help="Talk to the scheduling agent as a caller.")
    chat.add_argument(
        "--phone",
        required=True,
        help="Caller-ID phone number of the simulated incoming call.",
    )

    evaluate = subcommands.add_parser(
        "eval", help="Run the evaluation scenarios and the regression gate."
    )
    evaluate.add_argument(
        "--scenario",
        action="append",
        metavar="ID",
        help="Run only this scenario (e.g. E1); repeat for several. Default: all.",
    )
    evaluate.add_argument(
        "--update-baseline",
        action="store_true",
        help="Record this run's pass/fail results as the new baseline (refused on regression).",
    )
    evaluate.add_argument(
        "--record-evidence",
        action="store_true",
        help="Also write a compact, sanitised summary to evals/evidence/<run_id>.json.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Imported here so --help stays fast.
    if args.command == "chat":
        from care_agent.chat import run_chat

        return run_chat(args.phone)
    if args.command == "eval":
        from care_agent.evals.suite import run_eval

        return run_eval(
            args.scenario,
            update_baseline=args.update_baseline,
            record_evidence=args.record_evidence,
        )

    # argparse rejects unknown subcommands, so this is unreachable.
    raise AssertionError(f"unhandled command: {args.command}")
