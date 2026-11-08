"""Same shim for the group-filtering script."""

from __future__ import annotations

import sys

from apm2splunk.cli import main

if __name__ == "__main__":
    sys.exit(main(["forward"]))
