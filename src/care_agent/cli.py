"""Command-line interface.

Two subcommands, matching the two commands the README must document:

* ``chat`` - talk to the scheduling agent as a caller (implemented in M3).
* ``eval`` - run the scenario suite and the regression gate (implemented in M4).

Both are placeholders in M0 and exit with ``EXIT_NOT_IMPLEMENTED``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from care_agent import __version__

EXIT_OK = 0
EXIT_NOT_IMPLEMENTED = 2


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

    subcommands.add_parser("eval", help="Run the scenario suite and the regression gate.")

    return parser


def _not_implemented(command: str, milestone: str) -> int:
    print(f"'{command}' is not implemented yet (planned for {milestone}).", file=sys.stderr)
    return EXIT_NOT_IMPLEMENTED


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "chat":
        return _not_implemented("chat", "M3")
    if args.command == "eval":
        return _not_implemented("eval", "M4")

    # argparse rejects unknown subcommands, so this is unreachable.
    raise AssertionError(f"unhandled command: {args.command}")
