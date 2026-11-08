"""Forward ManageEngine APM monitor data to Splunk HTTP Event Collector.

Kept as a thin shim so an existing Splunk scripted input pointing at
``apm_to_splunk.py`` keeps working after the rewrite. New deployments should use
the ``apm2splunk`` command instead; see README.md.

The old module-level constants are gone on purpose. A credential in a file that
gets committed is a credential that has to be rotated, and an address in a file
cannot be changed without editing code. Configure with environment variables
(prefixed APM2SPLUNK_) or a config file.
"""

from __future__ import annotations

import sys

from apm2splunk.cli import main

if __name__ == "__main__":
    sys.exit(main(["forward"]))
