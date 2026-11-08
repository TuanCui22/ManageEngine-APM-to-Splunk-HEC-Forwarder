"""Forward APM monitor data for named monitor groups to Splunk HEC.

Kept as a thin entry point so an existing Splunk scripted input pointing at
``scriptFilterGroups.py`` keeps working. Group filtering is now a flag on the
shared CLI, so this name and ``apm_to_splunk.py`` run the same code path.

Set the groups with ``--group NAME`` (repeatable) or
``APM2SPLUNK_GROUP_NAMES="Group A,Group B"``. With no group set, every monitor is
forwarded.
"""

from __future__ import annotations

import sys

from apm2splunk.cli import main

if __name__ == "__main__":
    sys.exit(main(["forward"]))
