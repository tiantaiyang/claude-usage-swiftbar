"""Pure rendering of a Snapshot into SwiftBar plugin output.

SwiftBar treats every line before the first '---' as a menu-bar title and
cycles between them, so exactly one title line is emitted.
"""

import datetime as dt
from typing import List, NamedTuple, Optional, Sequence

from .config import CRIT_COLOR, MUTED_COLOR, WARN_COLOR, Config
from .model import (SEVERITY_CRITICAL, SEVERITY_NORMAL, SEVERITY_ORDER,
                    SEVERITY_WARNING, Snapshot)

FILLED = "▓"
EMPTY = "░"
STALE_MARK = "⌛"
WARN_MARK = "⚠️"
UNKNOWN_MARK = "?"
ABSENT_MARK = "—"

TITLE_KINDS = ("session", "weekly_all")
SPEND_LABEL = "Extra usage"
ROW_PARAMS = "font=Menlo size=12"

SIGN_IN_HINT = "Run: claude /login"
TOKEN_HINT = ("Claude Code refreshes it on next use; "
              "this plugin never refreshes tokens")

SEVERITY_COLORS = {SEVERITY_WARNING: WARN_COLOR, SEVERITY_CRITICAL: CRIT_COLOR}


class ViewState(NamedTuple):
    kind: str
    detail: str = ""
    retry_at: Optional[dt.datetime] = None


STATE_OK = ViewState("ok")


def bar(percent: float, width: int) -> str:
    """Proportional bar; any non-zero percent shows at least one block."""
    if width <= 0:
        return ""
    try:
        value = float(percent)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        filled = 0
    else:
        filled = max(1, min(width, int(value / 100 * width)))
    return FILLED * filled + EMPTY * (width - filled)


def _percent_text(percent: float) -> str:
    return "{:.0f}%".format(percent)


def _item(text: str, *params: str) -> str:
    extras = [param for param in params if param]
    return "{} | {}".format(text, " ".join(extras)) if extras else text


def _color_param(severity: str) -> str:
    color = SEVERITY_COLORS.get(severity)
    return "color={}".format(color) if color else ""


def _humanise_delta(delta: dt.timedelta) -> str:
    total = delta.total_seconds()
    if total <= 0:
        return "now"
    days = int(total // 86400)
    remainder = total - days * 86400
    hours = int(remainder // 3600)
    minutes = int((remainder % 3600) // 60)
    if days:
        return "in {}d {}h".format(days, hours)
    if hours:
        return "in {}h {}m".format(hours, minutes)
    return "in {}m".format(minutes)


def _reset_text(resets_at: Optional[dt.datetime],
                now: dt.datetime) -> str:
    if resets_at is None:
        return ""
    local = resets_at.astimezone()
    when = (local.strftime("%H:%M") if local.date() == now.astimezone().date()
            else local.strftime("%a %m-%d %H:%M"))
    return "resets {} ({})".format(when, _humanise_delta(resets_at - now))


def _label_width(snapshot: Optional[Snapshot]) -> int:
    labels = [SPEND_LABEL]
    if snapshot is not None:
        labels.extend(row.label for row in snapshot.limits)
    return max(len(label) for label in labels)


def _gauge_row(label: str, percent: float, trailing: str, severity: str,
               width: int, cfg: Config) -> str:
    body = "{:<{}} {:>4}  {}  {}".format(
        label, width, _percent_text(percent), bar(percent, cfg.bar_width),
        trailing).rstrip()
    return _item(body, ROW_PARAMS, _color_param(severity))


def _title(snapshot: Optional[Snapshot], state: ViewState,
           cfg: Config) -> str:
    if state.kind == "not_signed_in":
        return "{} {}".format(cfg.glyph, ABSENT_MARK)
    percents = [] if snapshot is None else [
        snapshot.percent_for_kind(kind) for kind in TITLE_KINDS]
    parts = [_percent_text(value) for value in percents if value is not None]
    if not parts:
        return "{} {}".format(cfg.glyph, UNKNOWN_MARK)
    if snapshot.spend is not None and _is_elevated(snapshot.spend.severity):
        parts.append(WARN_MARK)
    text = "{} {}".format(cfg.glyph, " · ".join(parts))
    if state.kind != "ok":
        text += " " + STALE_MARK
    return _item(text, _color_param(snapshot.worst_severity()))


def _is_elevated(severity: str) -> bool:
    return SEVERITY_ORDER.get(severity, 0) > SEVERITY_ORDER[SEVERITY_NORMAL]


def _header_block(plan_label: str, state: ViewState,
                  now: dt.datetime) -> List[str]:
    lines = [_item("Claude usage — {}".format(plan_label),
                   "size=12", "color=" + MUTED_COLOR)]
    if state.kind == "ok":
        return lines
    detail = state.detail or "Usage data unavailable"
    if state.retry_at is not None:
        detail = "{} until {}".format(
            detail, state.retry_at.astimezone().strftime("%H:%M"))
    lines.append(_item(detail, "color=" + CRIT_COLOR))
    if state.kind == "not_signed_in":
        lines.append(_item(SIGN_IN_HINT, "size=11", "color=" + MUTED_COLOR))
    elif state.kind == "token_expired":
        lines.append(_item(TOKEN_HINT, "size=11", "color=" + MUTED_COLOR))
    return lines


def _limit_block(snapshot: Optional[Snapshot], now: dt.datetime,
                 width: int, cfg: Config) -> List[str]:
    if snapshot is None:
        return []
    return [_gauge_row(row.label, row.percent,
                       _reset_text(row.resets_at, now), row.severity,
                       width, cfg)
            for row in snapshot.limits]


def _spend_block(snapshot: Optional[Snapshot], width: int,
                 cfg: Config) -> List[str]:
    if snapshot is None or snapshot.spend is None:
        return []
    spend = snapshot.spend
    trailing = "{} / {}".format(spend.used_text, spend.limit_text)
    if _is_elevated(spend.severity):
        trailing += " " + WARN_MARK
    lines = [_gauge_row(SPEND_LABEL, spend.percent, trailing, spend.severity,
                        width, cfg)]
    if spend.note:
        lines.append(_item(spend.note, "size=11", "color=" + MUTED_COLOR))
    return lines


def _footer_block(snapshot: Optional[Snapshot], cfg: Config) -> List[str]:
    lines = []
    if snapshot is not None:
        lines.append(_item(
            "Updated " + snapshot.fetched_at.astimezone().strftime("%H:%M:%S"),
            "size=11", "color=" + MUTED_COLOR))
    lines.append(_item("Refresh now", "refresh=true"))
    lines.append(_item("Open usage page", "href=" + cfg.usage_page_url))
    return lines


def _join(blocks: Sequence[Sequence[str]]) -> str:
    return "\n---\n".join("\n".join(block) for block in blocks if block)


def render(snapshot: Optional[Snapshot], plan_label: str, state: ViewState,
           now: dt.datetime, cfg: Config) -> str:
    """Build the full SwiftBar output. Never raises on partial data."""
    if snapshot is not None and not snapshot.limits:
        snapshot = None
    width = _label_width(snapshot)
    return _join([
        [_title(snapshot, state, cfg)],
        _header_block(plan_label, state, now),
        _limit_block(snapshot, now, width, cfg),
        _spend_block(snapshot, width, cfg),
        _footer_block(snapshot, cfg),
    ])
