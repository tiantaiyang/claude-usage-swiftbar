#!/usr/bin/python3
# <bitbar.title>Claude Usage</bitbar.title>
# <bitbar.version>v1.0.0</bitbar.version>
# <bitbar.author>tiantaiyang</bitbar.author>
# <bitbar.desc>Shows Claude session, weekly and extra-usage quota in the menu bar.</bitbar.desc>
# <bitbar.dependencies>python3</bitbar.dependencies>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
"""SwiftBar entry point. Resolves the repo (this file is usually a symlink)
and delegates everything to claude_usage.cli."""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from claude_usage.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
