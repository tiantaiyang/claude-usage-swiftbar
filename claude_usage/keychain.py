"""Read the Claude Code OAuth credentials from the login keychain.

Read-only by design. The token is held in memory only: Credentials redacts it
in repr/str so it cannot leak into a log line or an error message.
"""

import json
import subprocess
from typing import Any, Callable, NamedTuple, Optional, Sequence, Tuple

from .config import Config

SECURITY_BIN = "/usr/bin/security"
OAUTH_SECTION = "claudeAiOauth"
SUBPROCESS_TIMEOUT = 10


class NotSignedIn(Exception):
    """No usable Claude Code credentials in the keychain."""


class Credentials(NamedTuple):
    access_token: str
    subscription_type: Optional[str]
    rate_limit_tier: Optional[str]

    def __repr__(self) -> str:
        return ("Credentials(access_token=<redacted>, subscription_type={!r}, "
                "rate_limit_tier={!r})").format(self.subscription_type,
                                                self.rate_limit_tier)

    __str__ = __repr__


Runner = Callable[..., Tuple[int, str, str]]


def _run(argv: Sequence[str],
         timeout: Optional[float] = None) -> Tuple[int, str, str]:
    completed = subprocess.run(argv, capture_output=True, text=True,
                               timeout=timeout, check=False)
    return completed.returncode, completed.stdout, completed.stderr


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def read_credentials(cfg: Config,
                     runner: Optional[Runner] = None) -> Credentials:
    """Return the current credentials, or raise NotSignedIn."""
    argv = [SECURITY_BIN, "find-generic-password", "-s",
            cfg.keychain_service, "-w"]
    run = runner or _run
    try:
        returncode, stdout, _ = run(argv, timeout=SUBPROCESS_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        raise NotSignedIn("could not query the keychain: {}".format(
            error.__class__.__name__))
    if returncode != 0 or not stdout.strip():
        raise NotSignedIn("no Claude Code credentials in the keychain")
    try:
        payload = json.loads(stdout)
    except ValueError:
        raise NotSignedIn("keychain entry was not valid JSON")
    section = payload.get(OAUTH_SECTION) if isinstance(payload, dict) else None
    if not isinstance(section, dict):
        raise NotSignedIn("keychain entry has no Claude subscription section")
    token = _text(section.get("accessToken"))
    if token is None:
        raise NotSignedIn("keychain entry has no access token")
    return Credentials(
        access_token=token,
        subscription_type=_text(section.get("subscriptionType")),
        rate_limit_tier=_text(section.get("rateLimitTier")),
    )
