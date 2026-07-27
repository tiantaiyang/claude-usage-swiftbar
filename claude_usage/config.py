"""Every tunable lives here, each overridable by environment variable.

No caller hardcodes an endpoint, threshold, or path.
"""

import os
from typing import Mapping, NamedTuple, Optional

ENV_PREFIX = "CLAUDE_USAGE_"

DEFAULT_API_URL = "https://api.anthropic.com/api/oauth/usage"
DEFAULT_BETA_HEADER = "oauth-2025-04-20"
DEFAULT_KEYCHAIN_SERVICE = "Claude Code-credentials"
DEFAULT_USAGE_PAGE_URL = "https://claude.ai/settings/usage"
DEFAULT_TIMEOUT = 8.0
DEFAULT_WARN_PCT = 90
DEFAULT_CRIT_PCT = 95
DEFAULT_BAR_WIDTH = 10
DEFAULT_GLYPH = "◱"
# Native SF Symbol: monochrome, vector, and it follows the menu bar's
# light/dark appearance. Set the env var to "" to fall back to the glyph.
DEFAULT_SFIMAGE = "gauge.medium"
DEFAULT_STALE_AFTER = 900
DEFAULT_BACKOFF = 300
# Rendering runs far more often than this so the countdown moves;
# only a cache older than the TTL triggers a real request.
DEFAULT_FETCH_TTL = 120
DEFAULT_CACHE_PATH = "~/Library/Caches/claude-usage-swiftbar/snapshot.json"

# Light-mode, dark-mode pairs; SwiftBar picks by system appearance. Usage
# numbers are deliberately left uncoloured so they stay legible in the menu
# bar; these only tint error messages and de-emphasised metadata.
CRIT_COLOR = "#C0392B,#FF6B6B"
# A single value applies the same colour in both appearances. #888888 read as
# a near-invisible light grey against a pale, translucent light-mode menu --
# this pair is a dark grey for light mode and a light grey for dark mode, each
# with enough contrast to read as de-emphasised without disappearing.
MUTED_COLOR = "#48484A,#D1D1D6"


class Config(NamedTuple):
    api_url: str
    beta_header: str
    timeout: float
    warn_pct: int
    crit_pct: int
    bar_width: int
    glyph: str
    sfimage: str
    stale_after: int
    backoff_seconds: int
    fetch_ttl: int
    cache_path: str
    keychain_service: str
    usage_page_url: str
    user_agent: str


def _get_raw(env: Mapping[str, str], name: str) -> Optional[str]:
    """Unlike _get, distinguishes "unset" from "explicitly empty"."""
    return env.get(ENV_PREFIX + name)


def _get(env: Mapping[str, str], name: str) -> Optional[str]:
    value = env.get(ENV_PREFIX + name)
    return value if value else None


def _as_float(raw: Optional[str], default: float) -> float:
    try:
        return float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _as_int(raw: Optional[str], default: int) -> int:
    try:
        return int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def load_config(env: Optional[Mapping[str, str]] = None) -> Config:
    """Build an immutable Config, falling back to defaults on bad input."""
    env = os.environ if env is None else env
    cache_path = _get(env, "CACHE_PATH") or DEFAULT_CACHE_PATH
    from . import __version__

    return Config(
        api_url=_get(env, "API_URL") or DEFAULT_API_URL,
        beta_header=_get(env, "BETA_HEADER") or DEFAULT_BETA_HEADER,
        timeout=_as_float(_get(env, "TIMEOUT"), DEFAULT_TIMEOUT),
        warn_pct=_as_int(_get(env, "WARN_PCT"), DEFAULT_WARN_PCT),
        crit_pct=_as_int(_get(env, "CRIT_PCT"), DEFAULT_CRIT_PCT),
        bar_width=_as_int(_get(env, "BAR_WIDTH"), DEFAULT_BAR_WIDTH),
        glyph=_get(env, "GLYPH") or DEFAULT_GLYPH,
        sfimage=(DEFAULT_SFIMAGE if _get_raw(env, "SFIMAGE") is None
                 else _get_raw(env, "SFIMAGE")),
        stale_after=_as_int(_get(env, "STALE_AFTER"), DEFAULT_STALE_AFTER),
        backoff_seconds=_as_int(_get(env, "BACKOFF"), DEFAULT_BACKOFF),
        fetch_ttl=_as_int(_get(env, "FETCH_TTL"), DEFAULT_FETCH_TTL),
        cache_path=os.path.abspath(os.path.expanduser(cache_path)),
        keychain_service=(_get(env, "KEYCHAIN_SERVICE")
                          or DEFAULT_KEYCHAIN_SERVICE),
        usage_page_url=_get(env, "PAGE_URL") or DEFAULT_USAGE_PAGE_URL,
        user_agent="claude-usage-swiftbar/{} (+macOS menubar plugin)".format(
            __version__),
    )
