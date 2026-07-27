"""Pure normalisation of the /api/oauth/usage payload into immutable rows.

The endpoint is undocumented, so unknown limit kinds are surfaced with a
humanised label rather than dropped -- the payload already carries several
null placeholder buckets that may become real later.
"""

import datetime as dt
from typing import Any, Dict, NamedTuple, Optional, Tuple

from .config import Config

SEVERITY_NORMAL = "normal"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"
SEVERITY_ORDER = {SEVERITY_NORMAL: 0, SEVERITY_WARNING: 1,
                  SEVERITY_CRITICAL: 2}

KIND_LABELS = {
    "session": "Session (5h)",
    "weekly_all": "Weekly (all)",
    "weekly_oauth_apps": "Weekly (apps)",
}

# Legacy mirrors, used only when the canonical limits[] array is absent.
LEGACY_KEYS = (
    ("five_hour", "session", "session", True),
    ("seven_day", "weekly_all", "weekly", False),
    ("seven_day_opus", "weekly_opus", "weekly", False),
    ("seven_day_sonnet", "weekly_sonnet", "weekly", False),
    ("seven_day_oauth_apps", "weekly_oauth_apps", "weekly", False),
)

CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}

NO_PURCHASE_NOTE = "Credit purchases unavailable on this plan"


class LimitRow(NamedTuple):
    kind: str
    label: str
    percent: float
    resets_at: Optional[dt.datetime]
    severity: str
    is_active: bool
    group: str


class SpendRow(NamedTuple):
    percent: float
    used_text: str
    limit_text: str
    severity: str
    note: Optional[str]


class Snapshot(NamedTuple):
    limits: Tuple[LimitRow, ...]
    spend: Optional[SpendRow]
    fetched_at: dt.datetime

    def percent_for_kind(self, kind: str) -> Optional[float]:
        for row in self.limits:
            if row.kind == kind:
                return row.percent
        return None

    def reset_for_kind(self, kind: str) -> Optional[dt.datetime]:
        for row in self.limits:
            if row.kind == kind:
                return row.resets_at
        return None

    def max_limit_percent(self) -> float:
        """Highest quota limit. Excludes spend, which is not a quota."""
        return max((row.percent for row in self.limits), default=0.0)


def humanise(token: str) -> str:
    """'nimbus_quill' -> 'Nimbus Quill'; leaves '5x' alone."""
    words = [word for word in str(token).replace("-", "_").split("_") if word]
    return " ".join(
        word[0].upper() + word[1:] if word[:1].isalpha() else word
        for word in words
    ) or str(token)


def parse_timestamp(raw: Any) -> Optional[dt.datetime]:
    """Parse an ISO-8601 instant. Python 3.9 rejects a trailing 'Z'."""
    if not isinstance(raw, str) or not raw:
        return None
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _severity(raw: Any, percent: float, cfg: Config) -> str:
    if isinstance(raw, str) and raw in SEVERITY_ORDER:
        return raw
    if percent >= cfg.crit_pct:
        return SEVERITY_CRITICAL
    if percent >= cfg.warn_pct:
        return SEVERITY_WARNING
    return SEVERITY_NORMAL


def _percent(raw: Any) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _scoped_label(scope: Any) -> str:
    if isinstance(scope, dict):
        model = scope.get("model")
        if isinstance(model, dict):
            name = model.get("display_name") or model.get("id")
            if name:
                return "Weekly ({})".format(name)
        surface = scope.get("surface")
        if surface:
            return "Weekly ({})".format(surface)
    return "Weekly (scoped)"


def _label_for(kind: str, scope: Any) -> str:
    if kind == "weekly_scoped":
        return _scoped_label(scope)
    if kind in KIND_LABELS:
        return KIND_LABELS[kind]
    return humanise(kind)


def _row_from_limit(entry: Dict[str, Any], cfg: Config) -> Optional[LimitRow]:
    kind = entry.get("kind")
    if not isinstance(kind, str) or not kind:
        return None
    percent = _percent(entry.get("percent"))
    return LimitRow(
        kind=kind,
        label=_label_for(kind, entry.get("scope")),
        percent=percent,
        resets_at=parse_timestamp(entry.get("resets_at")),
        severity=_severity(entry.get("severity"), percent, cfg),
        is_active=bool(entry.get("is_active")),
        group=entry.get("group") or kind,
    )


def _rows_from_limits(payload: Dict[str, Any],
                      cfg: Config) -> Tuple[LimitRow, ...]:
    entries = payload.get("limits")
    if not isinstance(entries, list):
        return ()
    rows = [_row_from_limit(entry, cfg)
            for entry in entries if isinstance(entry, dict)]
    return tuple(row for row in rows if row is not None)


def _rows_from_legacy(payload: Dict[str, Any],
                      cfg: Config) -> Tuple[LimitRow, ...]:
    rows = []
    for key, kind, group, active in LEGACY_KEYS:
        entry = payload.get(key)
        if not isinstance(entry, dict):
            continue
        percent = _percent(entry.get("utilization"))
        rows.append(LimitRow(
            kind=kind,
            label=_label_for(kind, None),
            percent=percent,
            resets_at=parse_timestamp(entry.get("resets_at")),
            severity=_severity(entry.get("severity"), percent, cfg),
            is_active=active,
            group=group,
        ))
    return tuple(rows)


def format_money(amount: Any) -> Optional[str]:
    """Format from minor units and exponent -- never a hardcoded 100."""
    if not isinstance(amount, dict):
        return None
    try:
        minor = float(amount["amount_minor"])
        exponent = int(amount.get("exponent") or 0)
    except (KeyError, TypeError, ValueError):
        return None
    value = minor / (10 ** exponent)
    text = "{:.{}f}".format(value, max(exponent, 0))
    code = amount.get("currency")
    symbol = CURRENCY_SYMBOLS.get(code)
    if symbol:
        return symbol + text
    return "{} {}".format(text, code) if code else text


def _spend_from_payload(payload: Dict[str, Any],
                        cfg: Config) -> Optional[SpendRow]:
    spend = payload.get("spend")
    if not isinstance(spend, dict) or not spend.get("enabled"):
        return None
    used_text = format_money(spend.get("used"))
    limit_text = format_money(spend.get("limit"))
    if used_text is None or limit_text is None:
        return None
    percent = _percent(spend.get("percent"))
    note = None if spend.get("can_purchase_credits") else NO_PURCHASE_NOTE
    return SpendRow(
        percent=percent,
        used_text=used_text,
        limit_text=limit_text,
        severity=_severity(spend.get("severity"), percent, cfg),
        note=note,
    )


def normalize(payload: Any, cfg: Config, fetched_at: dt.datetime) -> Snapshot:
    """Build an immutable Snapshot. Never mutates the payload."""
    if not isinstance(payload, dict):
        return Snapshot(limits=(), spend=None, fetched_at=fetched_at)
    rows = _rows_from_limits(payload, cfg) or _rows_from_legacy(payload, cfg)
    return Snapshot(limits=rows,
                    spend=_spend_from_payload(payload, cfg),
                    fetched_at=fetched_at)


def plan_label(subscription_type: Optional[str],
               rate_limit_tier: Optional[str]) -> str:
    """'team' + 'default_claude_max_5x' -> 'Max 5x (team)'."""
    if rate_limit_tier:
        tier = rate_limit_tier
        for prefix in ("default_claude_", "default_"):
            if tier.startswith(prefix):
                tier = tier[len(prefix):]
                break
        base = humanise(tier)
    else:
        base = "Claude"
    if subscription_type:
        return "{} ({})".format(base, subscription_type)
    return base
