"""Shared test helpers: deterministic timezone, fixture loading, repo importability."""

import copy
import datetime as dt
import json
import os
import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Tests assert on local-time strings, so the zone must be pinned.
TEST_TZ = "Asia/Shanghai"

# 2026-07-27T11:09:00 in Asia/Shanghai.
NOW = dt.datetime.fromisoformat("2026-07-27T03:09:00+00:00")

FAKE_TOKEN = "sk-ant-oat01-FAKE-TOKEN-VALUE-DO-NOT-LEAK"


def pin_timezone():
    """Force a fixed local timezone. Returns a restore callable."""
    previous = os.environ.get("TZ")
    os.environ["TZ"] = TEST_TZ
    time.tzset()

    def restore():
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()

    return restore


def load_fixture(name="usage_full.json"):
    """Return a fresh deep copy so a test can never pollute another."""
    with (FIXTURES / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def deep_copy(value):
    return copy.deepcopy(value)


def fake_credentials_json(token=FAKE_TOKEN, subscription="team",
                          tier="default_claude_max_5x"):
    payload = {
        "claudeAiOauth": {
            "accessToken": token,
            "refreshToken": "sk-ant-ort01-FAKE-REFRESH",
            "expiresAt": 1785144625816,
            "subscriptionType": subscription,
            "rateLimitTier": tier,
        }
    }
    return json.dumps(payload)
