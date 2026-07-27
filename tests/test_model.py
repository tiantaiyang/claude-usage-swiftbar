import datetime as dt
import unittest

import support
from claude_usage import config, model

_UNSET = object()


class NormalizeTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(support.pin_timezone())
        self.cfg = config.load_config(env={})
        self.payload = support.load_fixture()

    def normalize(self, payload=_UNSET):
        # `is _UNSET`, not truthiness: an empty payload is a real test case.
        chosen = self.payload if payload is _UNSET else payload
        return model.normalize(chosen, self.cfg, support.NOW)

    def test_uses_canonical_limits_array(self):
        snapshot = self.normalize()
        self.assertEqual(
            [row.kind for row in snapshot.limits],
            ["session", "weekly_all", "weekly_scoped"],
        )

    def test_labels_for_known_kinds(self):
        snapshot = self.normalize()
        self.assertEqual(
            [row.label for row in snapshot.limits],
            ["Session (5h)", "Weekly (all)", "Weekly (Fable)"],
        )

    def test_percent_and_severity_come_from_payload(self):
        session = self.normalize().limits[0]
        self.assertEqual(session.percent, 61.0)
        self.assertEqual(session.severity, "normal")
        self.assertTrue(session.is_active)

    def test_resets_at_parsed_as_aware_datetime(self):
        session = self.normalize().limits[0]
        self.assertIsNotNone(session.resets_at)
        self.assertIsNotNone(session.resets_at.tzinfo)
        self.assertEqual(
            session.resets_at.astimezone(dt.timezone.utc).isoformat(),
            "2026-07-27T06:09:59.665815+00:00",
        )

    def test_null_resets_at_is_none_not_an_error(self):
        self.assertIsNone(self.normalize().limits[2].resets_at)

    def test_trailing_z_timestamp_is_accepted(self):
        payload = support.deep_copy(self.payload)
        payload["limits"][0]["resets_at"] = "2026-07-27T06:09:59Z"
        parsed = self.normalize(payload).limits[0].resets_at
        self.assertEqual(
            parsed.astimezone(dt.timezone.utc).isoformat(),
            "2026-07-27T06:09:59+00:00",
        )

    def test_unknown_kind_is_surfaced_generically_not_dropped(self):
        payload = support.deep_copy(self.payload)
        payload["limits"].append({
            "kind": "nimbus_quill",
            "group": "weekly",
            "percent": 12,
            "severity": "normal",
            "resets_at": None,
            "scope": None,
            "is_active": False,
        })
        labels = [row.label for row in self.normalize(payload).limits]
        self.assertIn("Nimbus Quill", labels)

    def test_severity_derived_from_thresholds_when_absent(self):
        payload = support.deep_copy(self.payload)
        for row, percent in zip(payload["limits"], (10, 85, 97)):
            row.pop("severity")
            row["percent"] = percent
        severities = [row.severity for row in self.normalize(payload).limits]
        self.assertEqual(severities, ["normal", "warning", "critical"])

    def test_falls_back_to_legacy_keys_when_limits_absent(self):
        payload = support.deep_copy(self.payload)
        payload.pop("limits")
        snapshot = self.normalize(payload)
        self.assertEqual([row.kind for row in snapshot.limits],
                         ["session", "weekly_all"])
        self.assertEqual(snapshot.limits[0].percent, 61.0)
        self.assertEqual(snapshot.limits[1].percent, 25.0)

    def test_missing_limits_and_legacy_yields_no_rows_without_raising(self):
        snapshot = self.normalize({})
        self.assertEqual(snapshot.limits, ())
        self.assertIsNone(snapshot.spend)

    def test_normalize_does_not_mutate_input(self):
        before = support.deep_copy(self.payload)
        self.normalize()
        self.assertEqual(self.payload, before)

    def test_rows_are_immutable(self):
        row = self.normalize().limits[0]
        with self.assertRaises(AttributeError):
            row.percent = 5

    def test_reset_for_kind_returns_the_matching_reset_time(self):
        snapshot = self.normalize()
        self.assertEqual(snapshot.reset_for_kind("session"),
                         snapshot.limits[0].resets_at)

    def test_reset_for_kind_is_none_for_unknown_kind(self):
        self.assertIsNone(self.normalize().reset_for_kind("nope"))

    def test_reset_for_kind_is_none_when_row_has_no_reset(self):
        self.assertIsNone(self.normalize().reset_for_kind("weekly_scoped"))

    def test_limits_is_a_tuple(self):
        self.assertIsInstance(self.normalize().limits, tuple)


class SpendTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(support.pin_timezone())
        self.cfg = config.load_config(env={})
        self.payload = support.load_fixture()

    def spend(self, payload=_UNSET):
        chosen = self.payload if payload is _UNSET else payload
        return model.normalize(chosen, self.cfg, support.NOW).spend

    def test_money_formatted_from_minor_units_and_exponent(self):
        spend = self.spend()
        self.assertEqual(spend.used_text, "$50.25")
        self.assertEqual(spend.limit_text, "$50.00")

    def test_percent_and_severity(self):
        spend = self.spend()
        self.assertEqual(spend.percent, 100.0)
        self.assertEqual(spend.severity, "critical")

    def test_exponent_zero_is_not_divided_by_a_hardcoded_hundred(self):
        payload = support.deep_copy(self.payload)
        payload["spend"]["used"] = {"amount_minor": 1500, "currency": "JPY",
                                    "exponent": 0}
        self.assertEqual(self.spend(payload).used_text, "¥1500")

    def test_unknown_currency_falls_back_to_code(self):
        payload = support.deep_copy(self.payload)
        payload["spend"]["used"] = {"amount_minor": 500, "currency": "XYZ",
                                    "exponent": 2}
        self.assertEqual(self.spend(payload).used_text, "5.00 XYZ")

    def test_note_when_credits_cannot_be_purchased(self):
        self.assertEqual(self.spend().note,
                         "Credit purchases unavailable on this plan")

    def test_no_note_when_credits_can_be_purchased(self):
        payload = support.deep_copy(self.payload)
        payload["spend"]["can_purchase_credits"] = True
        self.assertIsNone(self.spend(payload).note)

    def test_disabled_spend_is_omitted(self):
        payload = support.deep_copy(self.payload)
        payload["spend"]["enabled"] = False
        self.assertIsNone(self.spend(payload))


class PlanLabelTest(unittest.TestCase):
    def test_tier_and_subscription(self):
        self.assertEqual(
            model.plan_label("team", "default_claude_max_5x"), "Max 5x (team)")

    def test_tier_only(self):
        self.assertEqual(model.plan_label(None, "default_claude_max_20x"),
                         "Max 20x")

    def test_unknown_tier_is_humanised_not_dropped(self):
        self.assertEqual(model.plan_label("pro", "some_new_tier"),
                         "Some New Tier (pro)")

    def test_no_information_falls_back(self):
        self.assertEqual(model.plan_label(None, None), "Claude")


if __name__ == "__main__":
    unittest.main()
