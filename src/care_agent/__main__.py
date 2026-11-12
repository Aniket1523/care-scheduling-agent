"""Entry point for ``python -m care_agent``."""

import sys

from care_agent.cli import main

if __name__ == "__main__":
    sys.exit(main())
