import unittest

import support
from claude_usage import config, model, render
from claude_usage.config import CRIT_COLOR, MUTED_COLOR


def sections(text):
    """Split SwiftBar output into [title_block, *menu_blocks]."""
    return [block.splitlines() for block in text.split("\n---\n")]


class RenderOkTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(support.pin_timezone())
        self.cfg = config.load_config(env={})
        self.snapshot = model.normalize(support.load_fixture(), self.cfg,
                                        support.NOW)
        self.text = render.render(self.snapshot, "Max 5x (team)",
                                  render.STATE_OK, support.NOW, self.cfg)
        self.lines = self.text.splitlines()

    def test_menu_bar_title_matches_agreed_format(self):
        # session% + 5h countdown + spend warning; weekly lives in the menu.
        self.assertEqual(self.lines[0], "◱ 61% · 3h00")

    def test_exactly_one_line_before_first_separator(self):
        # More than one line makes SwiftBar cycle the title.
        self.assertEqual(len(sections(self.text)[0]), 1)

    def test_plan_header_present(self):
        self.assertIn("Claude usage — Max 5x (team)", self.text)

    def test_limit_rows_are_column_aligned(self):
        self.assertIn(
            "Session (5h)    61%  ▓▓▓▓▓▓░░░░  resets 14:09 (in 3h 0m)",
            self.text)
        weekly = ("Weekly (all)    25%  ▓▓░░░░░░░░  "
                  "resets Sun 08-02 01:59 (in 5d 14h)")
        self.assertIn(weekly, self.text)

    def test_row_without_reset_time_has_no_trailing_whitespace(self):
        row = next(line for line in self.lines if "Weekly (Fable)" in line)
        body = row.split(" | ")[0]
        self.assertEqual(body,
                         "Weekly (Fable)   0%  ░░░░░░░░░░")

    def test_rows_use_monospace_font_for_alignment(self):
        row = next(line for line in self.lines if "Session (5h)" in line)
        self.assertIn("font=Menlo", row)

    def test_spend_row_shows_money_and_warning(self):
        self.assertIn(
            "Extra usage    100%  ▓▓▓▓▓▓▓▓▓▓  $50.25 / $50.00 ⚠️", self.text)

    def test_spend_note_rendered(self):
        self.assertIn("Credit purchases unavailable on this plan", self.text)

    def test_footer_actions(self):
        self.assertIn("Updated 11:09:00", self.text)
        self.assertIn("Refresh now | refresh=true", self.text)
        self.assertIn("href=" + self.cfg.usage_page_url, self.text)

    def test_title_is_never_coloured(self):
        self.assertNotIn("color=", self.lines[0])

    def test_limit_rows_are_never_coloured(self):
        for line in self.lines:
            if "font=Menlo" in line:
                self.assertNotIn("color=", line, line)


class RenderSeverityTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(support.pin_timezone())
        self.cfg = config.load_config(env={})

    def title_for(self, session_percent, severity):
        payload = support.load_fixture()
        payload["limits"][0]["percent"] = session_percent
        payload["limits"][0]["severity"] = severity
        snapshot = model.normalize(payload, self.cfg, support.NOW)
        text = render.render(snapshot, "Max 5x (team)", render.STATE_OK,
                             support.NOW, self.cfg)
        return text.splitlines()[0]

    def test_title_stays_uncoloured_at_every_severity(self):
        # A tinted title is hard to read against the menu bar; the percentage
        # and the warning glyph already carry the signal.
        for percent, severity in ((10, "normal"), (85, "warning"),
                                  (99, "critical")):
            title = self.title_for(percent, severity)
            self.assertNotIn("color=", title, severity)

    def test_title_still_reports_the_number_at_warning(self):
        self.assertEqual(self.title_for(85, "warning"), "◱ 85% · 3h00 · ⚠️")

    def test_rows_stay_uncoloured_at_every_severity(self):
        for severity in ("normal", "warning", "critical"):
            payload = support.load_fixture()
            payload["limits"][0]["severity"] = severity
            payload["limits"][0]["percent"] = 97
            payload["spend"]["severity"] = severity
            snapshot = model.normalize(payload, self.cfg, support.NOW)
            text = render.render(snapshot, "Max 5x (team)", render.STATE_OK,
                                 support.NOW, self.cfg)
            for line in text.splitlines():
                if "font=Menlo" in line:
                    self.assertNotIn("color=", line, severity)

    def test_secondary_lines_keep_their_muted_colour(self):
        # Only usage-driven colouring is dropped; de-emphasised metadata and
        # error messages keep theirs.
        text = render.render(
            model.normalize(support.load_fixture(), self.cfg, support.NOW),
            "Max 5x (team)", render.STATE_OK, support.NOW, self.cfg)
        self.assertIn("color=" + MUTED_COLOR, text)

    def test_degraded_detail_keeps_its_alert_colour(self):
        text = render.render(None, "Claude",
                             render.ViewState("not_signed_in", "nope"),
                             support.NOW, self.cfg)
        self.assertIn("color=" + CRIT_COLOR, text)

    def title_of(self, payload):
        snapshot = model.normalize(payload, self.cfg, support.NOW)
        return render.render(snapshot, "Max 5x (team)", render.STATE_OK,
                             support.NOW, self.cfg).splitlines()[0]

    def test_warns_when_the_session_limit_is_elevated(self):
        self.assertEqual(self.title_for(85, "warning"), "◱ 85% · 3h00 · ⚠️")

    def test_warns_on_weekly_even_when_session_is_low(self):
        payload = support.load_fixture()
        payload["limits"][1]["percent"] = 88
        payload["limits"][1]["severity"] = "warning"
        self.assertEqual(self.title_of(payload), "◱ 61% · 3h00 · ⚠️")

    def test_does_not_warn_for_extra_usage_alone(self):
        # Extra-usage credits can sit over their cap indefinitely. Letting that
        # drive the menu bar meant a permanent warning at 0% session usage.
        payload = support.load_fixture()
        payload["limits"][0]["percent"] = 0
        payload["spend"]["severity"] = "critical"
        payload["spend"]["percent"] = 100
        self.assertEqual(self.title_of(payload), "◱ 0% · 3h00")

    def test_warns_at_critical_severity(self):
        self.assertEqual(self.title_for(97, "critical"), "◱ 97% · 3h00 · ⚠️")

    def test_warning_derived_from_threshold_when_api_omits_severity(self):
        payload = support.load_fixture()
        payload["limits"][0]["percent"] = 90
        payload["limits"][0].pop("severity")
        self.assertEqual(self.title_of(payload), "◱ 90% · 3h00 · ⚠️")

    def test_no_warning_just_below_the_threshold(self):
        payload = support.load_fixture()
        payload["limits"][0]["percent"] = 79
        payload["limits"][0].pop("severity")
        self.assertEqual(self.title_of(payload), "◱ 79% · 3h00")


class RenderDegradedTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(support.pin_timezone())
        self.cfg = config.load_config(env={})
        self.snapshot = model.normalize(support.load_fixture(), self.cfg,
                                        support.NOW)

    def render_state(self, state, snapshot=None):
        return render.render(snapshot, "Max 5x (team)", state, support.NOW,
                             self.cfg)

    def test_not_signed_in(self):
        text = self.render_state(
            render.ViewState("not_signed_in", "Not signed in to Claude Code"))
        self.assertEqual(text.splitlines()[0], "◱ —")
        self.assertIn("Not signed in to Claude Code", text)
        self.assertIn("claude /login", text)

    def test_token_expired_keeps_cached_numbers_and_marks_them(self):
        text = self.render_state(
            render.ViewState("token_expired", "Token expired"), self.snapshot)
        self.assertEqual(text.splitlines()[0], "◱ 61% · 3h00 ⌛")
        self.assertIn("Token expired", text)
        self.assertIn("never", text.lower())

    def test_offline_shows_snapshot_age(self):
        text = self.render_state(
            render.ViewState("offline", "Offline — snapshot from 11:06"),
            self.snapshot)
        self.assertIn("⌛", text.splitlines()[0])
        self.assertIn("Offline — snapshot from 11:06", text)

    def test_rate_limited_reports_retry_time(self):
        retry = support.NOW.replace(minute=39)
        state = render.ViewState("rate_limited", "Rate limited", retry)
        text = self.render_state(state, self.snapshot)
        self.assertIn("Rate limited", text)
        self.assertIn("11:39", text)

    def test_schema_error_without_snapshot(self):
        text = self.render_state(
            render.ViewState("schema_error", "Unexpected response shape"))
        self.assertEqual(text.splitlines()[0], "◱ ?")
        self.assertIn("Unexpected response shape", text)

    def test_no_data_still_offers_refresh(self):
        text = self.render_state(render.ViewState("no_data", "No data yet"))
        self.assertEqual(text.splitlines()[0], "◱ ?")
        self.assertIn("Refresh now | refresh=true", text)

    def test_degraded_output_still_has_single_title_line(self):
        for state in ("not_signed_in", "schema_error", "no_data"):
            text = self.render_state(render.ViewState(state, "detail"))
            self.assertEqual(len(sections(text)[0]), 1, state)


class BarTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load_config(env={})

    def test_bar_endpoints_and_rounding(self):
        cases = {0: "░░░░░░░░░░", 25: "▓▓░░░░░░░░", 61: "▓▓▓▓▓▓░░░░",
                 100: "▓▓▓▓▓▓▓▓▓▓"}
        for percent, expected in cases.items():
            self.assertEqual(render.bar(percent, self.cfg.bar_width), expected,
                             percent)

    def test_tiny_nonzero_percent_still_shows_one_block(self):
        self.assertEqual(render.bar(1, self.cfg.bar_width),
                         "▓░░░░░░░░░")

    def test_out_of_range_percent_is_clamped(self):
        self.assertEqual(render.bar(140, self.cfg.bar_width), "▓▓▓▓▓▓▓▓▓▓")
        self.assertEqual(render.bar(-5, self.cfg.bar_width), "░░░░░░░░░░")



class CompactDeltaTest(unittest.TestCase):
    """The menu-bar countdown format: short enough to sit in the title."""

    def delta(self, **kwargs):
        import datetime as dt
        return render.compact_delta(dt.timedelta(**kwargs))

    def test_hours_are_zero_padded_to_two_minute_digits(self):
        self.assertEqual(self.delta(hours=2, minutes=8), "2h08")

    def test_exact_hour_shows_double_zero_minutes(self):
        self.assertEqual(self.delta(hours=3), "3h00")

    def test_seconds_do_not_round_the_minute_up(self):
        # 3h00m59s must read 3h00, not 3h01 -- the window has not moved on yet.
        self.assertEqual(self.delta(hours=3, seconds=59), "3h00")

    def test_under_an_hour_shows_minutes_only(self):
        self.assertEqual(self.delta(minutes=47), "47m")

    def test_one_minute_boundary(self):
        self.assertEqual(self.delta(minutes=1), "1m")

    def test_under_a_minute_is_not_shown_as_zero(self):
        self.assertEqual(self.delta(seconds=42), "<1m")

    def test_elapsed_window_reads_now(self):
        self.assertEqual(self.delta(seconds=0), "now")
        self.assertEqual(self.delta(seconds=-90), "now")

    def test_multi_day_stays_compact(self):
        # Not used by the session window, but must not print "134h50".
        self.assertEqual(self.delta(days=5, hours=14), "5d14h")

    def test_no_seconds_shown_above_a_minute(self):
        # 30s refresh would make a seconds digit jump in 30s steps.
        for text in (self.delta(minutes=5, seconds=30), self.delta(hours=1)):
            self.assertNotIn("s", text)


class TitleCountdownTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(support.pin_timezone())
        self.cfg = config.load_config(env={})

    def title(self, payload):
        snapshot = model.normalize(payload, self.cfg, support.NOW)
        return render.render(snapshot, "Max 5x (team)", render.STATE_OK,
                             support.NOW, self.cfg).splitlines()[0]

    def test_countdown_recomputed_from_now_not_from_fetch_time(self):
        payload = support.load_fixture()
        snapshot = model.normalize(payload, self.cfg, support.NOW)
        import datetime as dt
        later = support.NOW + dt.timedelta(minutes=90)
        first = render.render(snapshot, "p", render.STATE_OK, support.NOW,
                              self.cfg).splitlines()[0]
        second = render.render(snapshot, "p", render.STATE_OK, later,
                               self.cfg).splitlines()[0]
        self.assertIn("3h00", first)
        self.assertIn("1h30", second)

    def test_countdown_omitted_when_session_row_absent(self):
        payload = support.load_fixture()
        payload["limits"] = [row for row in payload["limits"]
                             if row["kind"] != "session"]
        title = self.title(payload)
        self.assertNotIn("h0", title)
        self.assertTrue(title.startswith("◱ 25%"), title)

    def test_countdown_omitted_when_reset_time_is_null(self):
        payload = support.load_fixture()
        payload["limits"][0]["resets_at"] = None
        self.assertEqual(self.title(payload), "◱ 61%")

    def test_weekly_percent_is_not_in_the_title(self):
        self.assertNotIn("25%", self.title(support.load_fixture()))


if __name__ == "__main__":
    unittest.main()
