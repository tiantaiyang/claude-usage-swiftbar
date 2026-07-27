"""Orchestration: read credentials, fetch usage, degrade gracefully, render.

run() never raises. SwiftBar shows stderr as a broken plugin, so every failure
becomes a rendered state instead.
"""

import datetime as dt
from typing import Any, Callable, Dict, NamedTuple, Optional, Tuple

from . import api, cache, config, keychain, model, render
from .config import Config
from .model import Snapshot


class Deps(NamedTuple):
    read_credentials: Callable[[Config], keychain.Credentials]
    fetch_usage: Callable[[str, Config], Dict[str, Any]]
    cache_load: Callable[[str], Optional[Dict[str, Any]]]
    cache_save: Callable[[str, Dict[str, Any]], None]


DEFAULT_DEPS = Deps(keychain.read_credentials, api.fetch_usage, cache.load,
                    cache.save)


def _record(payload: Dict[str, Any], now: dt.datetime,
            backoff_until: Optional[dt.datetime] = None) -> Dict[str, Any]:
    return {
        "version": cache.VERSION,
        "fetched_at": now.isoformat(),
        "payload": payload,
        "backoff_until": (backoff_until.isoformat() if backoff_until
                          else None),
    }


def _load_record(cfg: Config, deps: Deps) -> Optional[Dict[str, Any]]:
    try:
        record = deps.cache_load(cfg.cache_path)
    except Exception:
        return None
    return record if isinstance(record, dict) else None


def _store(cfg: Config, deps: Deps, record: Dict[str, Any]) -> None:
    """A cache failure must never take the menu bar down with it."""
    try:
        deps.cache_save(cfg.cache_path, record)
    except Exception:
        pass


def _cached_payload(record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if record is None:
        return {}
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


def _cached_snapshot(record: Optional[Dict[str, Any]], cfg: Config,
                     now: dt.datetime) -> Tuple[Optional[Snapshot], bool]:
    """Return (snapshot, is_stale); snapshot is None when unusable."""
    payload = _cached_payload(record)
    if not payload:
        return None, False
    fetched_at = model.parse_timestamp((record or {}).get("fetched_at")) or now
    snapshot = model.normalize(payload, cfg, fetched_at)
    if not snapshot.limits:
        return None, False
    is_stale = (now - fetched_at).total_seconds() > cfg.stale_after
    return snapshot, is_stale


def _offline_state(snapshot: Optional[Snapshot], is_stale: bool,
                   reason: str) -> render.ViewState:
    if snapshot is None:
        return render.ViewState("no_data", reason)
    detail = "Offline — snapshot from {}".format(
        snapshot.fetched_at.astimezone().strftime("%H:%M"))
    if is_stale:
        detail += " (stale)"
    return render.ViewState("offline", detail)


def _rate_limited_state(retry_at: Optional[dt.datetime]) -> render.ViewState:
    return render.ViewState("rate_limited", "Rate limited", retry_at)


def _resolve(cfg: Config, now: dt.datetime, deps: Deps,
             token: str) -> Tuple[Optional[Snapshot], render.ViewState]:
    record = _load_record(cfg, deps)
    backoff_until = model.parse_timestamp((record or {}).get("backoff_until"))
    snapshot, is_stale = _cached_snapshot(record, cfg, now)

    if backoff_until is not None and backoff_until > now:
        return snapshot, _rate_limited_state(backoff_until)

    try:
        payload = deps.fetch_usage(token, cfg)
    except api.TokenRejected as error:
        if snapshot is None:
            return None, render.ViewState("no_data", str(error))
        return snapshot, render.ViewState("token_expired", "Token expired")
    except api.RateLimited as error:
        seconds = error.retry_after or cfg.backoff_seconds
        retry_at = now + dt.timedelta(seconds=seconds)
        _store(cfg, deps, _record(_cached_payload(record), now, retry_at))
        return snapshot, _rate_limited_state(retry_at)
    except api.NetworkError as error:
        return snapshot, _offline_state(snapshot, is_stale, str(error))
    except api.SchemaError as error:
        if snapshot is None:
            return None, render.ViewState("schema_error", str(error))
        return snapshot, render.ViewState("schema_error", str(error))

    fresh = model.normalize(payload, cfg, now)
    _store(cfg, deps, _record(payload, now))
    if not fresh.limits:
        return snapshot, render.ViewState(
            "schema_error", "response contained no usage limits")
    return fresh, render.STATE_OK


def run(cfg: Config, now: dt.datetime, deps: Deps = DEFAULT_DEPS) -> str:
    """Produce SwiftBar output for the current state. Never raises."""
    try:
        credentials = deps.read_credentials(cfg)
    except keychain.NotSignedIn as error:
        return render.render(None, "Claude", render.ViewState(
            "not_signed_in", "Not signed in to Claude Code — {}".format(error)),
            now, cfg)
    except Exception as error:  # noqa: BLE001 -- must not break the menu bar
        return render.render(None, "Claude", render.ViewState(
            "error", "Keychain error: {}".format(error.__class__.__name__)),
            now, cfg)

    label = model.plan_label(credentials.subscription_type,
                             credentials.rate_limit_tier)
    try:
        snapshot, state = _resolve(cfg, now, deps, credentials.access_token)
    except Exception as error:  # noqa: BLE001 -- must not break the menu bar
        snapshot, state = None, render.ViewState(
            "error", "Unexpected failure: {}".format(error.__class__.__name__))
    return render.render(snapshot, label, state, now, cfg)


def main() -> int:
    cfg = config.load_config()
    print(run(cfg, dt.datetime.now(dt.timezone.utc)))
    return 0
