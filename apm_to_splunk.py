"""Forward ManageEngine APM monitor data to Splunk HTTP Event Collector.

Kept as a thin entry point so an existing Splunk scripted input pointing at
``apm_to_splunk.py`` keeps working. New deployments should use the
``apm2splunk`` command instead; see README.md.

Configuration comes from flags, environment variables (prefixed APM2SPLUNK_), or
a config file. No credential has a default.
"""

from __future__ import annotations

import sys

from apm2splunk.cli import main

if __name__ == "__main__":
    sys.exit(main(["forward"]))
