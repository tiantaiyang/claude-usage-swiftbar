"""Read-only client for the OAuth usage endpoint.

This module deliberately has no refresh path: rotating the refresh token from a
second process can sign the user out of Claude Code. On rejection it reports
and stops. Error messages never include the token.
"""

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional

from .config import Config


class UsageApiError(Exception):
    """Base class so callers can catch every failure mode at once."""


class TokenRejected(UsageApiError):
    """401/403 -- Claude Code must refresh or re-authenticate."""


class RateLimited(UsageApiError):
    def __init__(self, message: str,
                 retry_after: Optional[int] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class NetworkError(UsageApiError):
    """Transport failure or transient server error; retry later."""


class SchemaError(UsageApiError):
    """Reachable but the response was not a usage object."""


def _retry_after(error: urllib.error.HTTPError) -> Optional[int]:
    raw = None
    if error.headers is not None:
        raw = error.headers.get("Retry-After")
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _build_request(token: str, cfg: Config) -> urllib.request.Request:
    return urllib.request.Request(
        cfg.api_url,
        method="GET",
        headers={
            "Authorization": "Bearer " + token,
            "anthropic-beta": cfg.beta_header,
            "Accept": "application/json",
            "User-Agent": cfg.user_agent,
        },
    )


def _decode(raw: bytes) -> Dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        raise SchemaError("response was not JSON")
    if not isinstance(payload, dict):
        raise SchemaError("response was not a JSON object")
    return payload


def fetch_usage(token: str, cfg: Config,
                opener: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """GET the usage payload. Raises a UsageApiError subclass on failure."""
    request = _build_request(token, cfg)
    open_url = opener or urllib.request.urlopen
    try:
        response = open_url(request, timeout=cfg.timeout)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise TokenRejected("access token rejected (HTTP {})".format(
                error.code))
        if error.code == 429:
            raise RateLimited("rate limited by the API",
                              retry_after=_retry_after(error))
        if error.code >= 500:
            raise NetworkError("server error (HTTP {})".format(error.code))
        raise SchemaError("unexpected response (HTTP {})".format(error.code))
    except (urllib.error.URLError, socket.timeout, OSError) as error:
        raise NetworkError("could not reach the usage endpoint: {}".format(
            error.__class__.__name__))
    try:
        with response:
            raw = response.read()
    except (OSError, socket.timeout):
        raise NetworkError("connection dropped while reading the response")
    return _decode(raw)
