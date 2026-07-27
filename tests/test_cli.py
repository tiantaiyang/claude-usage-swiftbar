import datetime as dt
import json
import unittest

import support
from claude_usage import api, cli, config, keychain


class FakeDeps:
    def __init__(self, credentials=None, fetch_result=None, cached=None):
        self._credentials = credentials or keychain.Credentials(
            support.FAKE_TOKEN, "team", "default_claude_max_5x")
        self._fetch_result = (fetch_result if fetch_result is not None
                              else support.load_fixture())
        self.cached = cached
        self.saved = []
        self.fetch_calls = 0

    def read_credentials(self, cfg):
        if isinstance(self._credentials, Exception):
            raise self._credentials
        return self._credentials

    def fetch_usage(self, token, cfg):
        self.fetch_calls += 1
        if isinstance(self._fetch_result, Exception):
            raise self._fetch_result
        return self._fetch_result

    def cache_load(self, path):
        return self.cached

    def cache_save(self, path, record):
        self.saved.append(record)

    def as_deps(self):
        return cli.Deps(self.read_credentials, self.fetch_usage,
                        self.cache_load, self.cache_save)


# Default cache age sits beyond fetch_ttl but well inside stale_after, i.e.
# "there is a cache, but it needs refreshing" -- otherwise the TTL
# short-circuit returns before a fetch is ever attempted.
STALE_ENOUGH_TO_REFETCH = 300


def cached_record(fetched_at=None, backoff_until=None):
    if fetched_at is None:
        fetched_at = support.NOW - dt.timedelta(
            seconds=STALE_ENOUGH_TO_REFETCH)
    return {
        "version": 1,
        "fetched_at": fetched_at.isoformat(),
        "payload": support.load_fixture(),
        "backoff_until": backoff_until.isoformat() if backoff_until else None,
    }


class RunTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(support.pin_timezone())
        self.cfg = config.load_config(env={})

    def run_with(self, fake):
        return cli.run(self.cfg, support.NOW, fake.as_deps())

    def test_happy_path_renders_live_numbers(self):
        fake = FakeDeps()
        text = self.run_with(fake)
        self.assertEqual(text.splitlines()[0], "◱ 61% · 3h00 · ⚠️")
        self.assertEqual(fake.fetch_calls, 1)

    def test_happy_path_persists_the_payload(self):
        fake = FakeDeps()
        self.run_with(fake)
        self.assertEqual(len(fake.saved), 1)
        self.assertEqual(fake.saved[0]["payload"]["five_hour"]["utilization"],
                         61.0)

    def test_persisted_record_contains_no_token(self):
        fake = FakeDeps()
        self.run_with(fake)
        self.assertNotIn(support.FAKE_TOKEN, json.dumps(fake.saved[0]))
        self.assertNotIn("sk-ant", json.dumps(fake.saved[0]))

    def test_not_signed_in_skips_the_network(self):
        fake = FakeDeps(credentials=keychain.NotSignedIn("no keychain item"))
        text = self.run_with(fake)
        self.assertEqual(text.splitlines()[0], "◱ —")
        self.assertEqual(fake.fetch_calls, 0)
        self.assertEqual(fake.saved, [])

    def test_token_rejected_falls_back_to_cache(self):
        fake = FakeDeps(fetch_result=api.TokenRejected("401"),
                        cached=cached_record())
        text = self.run_with(fake)
        self.assertEqual(text.splitlines()[0], "◱ 61% · 3h00 · ⚠️ ⌛")
        self.assertIn("Token expired", text)

    def test_token_rejected_without_cache_reports_the_problem(self):
        fake = FakeDeps(fetch_result=api.TokenRejected("401"))
        text = self.run_with(fake)
        self.assertEqual(text.splitlines()[0], "◱ ?")

    def test_network_error_falls_back_to_cache(self):
        fake = FakeDeps(fetch_result=api.NetworkError("offline"),
                        cached=cached_record())
        text = self.run_with(fake)
        self.assertIn("⌛", text.splitlines()[0])
        self.assertIn("Offline", text)

    def test_stale_cache_is_labelled_stale(self):
        old = support.NOW - dt.timedelta(seconds=self.cfg.stale_after + 60)
        fake = FakeDeps(fetch_result=api.NetworkError("offline"),
                        cached=cached_record(fetched_at=old))
        text = self.run_with(fake)
        self.assertIn("stale", text.lower())

    def test_schema_error_is_reported(self):
        fake = FakeDeps(fetch_result=api.SchemaError("unexpected shape"))
        text = self.run_with(fake)
        self.assertEqual(text.splitlines()[0], "◱ ?")
        self.assertIn("unexpected shape", text)

    def test_rate_limited_persists_a_backoff(self):
        error = api.RateLimited("429", retry_after=600)
        fake = FakeDeps(fetch_result=error, cached=cached_record())
        text = self.run_with(fake)
        self.assertIn("Rate limited", text)
        self.assertIsNotNone(fake.saved[0]["backoff_until"])

    def test_active_backoff_skips_the_network(self):
        future = support.NOW + dt.timedelta(minutes=5)
        fake = FakeDeps(cached=cached_record(backoff_until=future))
        text = self.run_with(fake)
        self.assertEqual(fake.fetch_calls, 0)
        self.assertIn("Rate limited", text)

    def test_expired_backoff_allows_a_fetch(self):
        past = support.NOW - dt.timedelta(minutes=5)
        fake = FakeDeps(cached=cached_record(backoff_until=past))
        self.run_with(fake)
        self.assertEqual(fake.fetch_calls, 1)

    def test_unexpected_exception_still_produces_valid_output(self):
        fake = FakeDeps(fetch_result=RuntimeError("boom"))
        text = self.run_with(fake)
        self.assertEqual(text.splitlines()[0], "◱ ?")
        self.assertIn("Refresh now | refresh=true", text)

    def test_cache_write_failure_does_not_break_rendering(self):
        fake = FakeDeps()

        def exploding_save(path, record):
            raise OSError("read-only filesystem")

        deps = cli.Deps(fake.read_credentials, fake.fetch_usage,
                        fake.cache_load, exploding_save)
        text = cli.run(self.cfg, support.NOW, deps)
        self.assertEqual(text.splitlines()[0], "◱ 61% · 3h00 · ⚠️")

    def test_corrupt_cache_does_not_break_degraded_rendering(self):
        fake = FakeDeps(fetch_result=api.NetworkError("offline"),
                        cached={"version": 1, "payload": "not-a-dict"})
        text = self.run_with(fake)
        self.assertEqual(text.splitlines()[0], "◱ ?")

    def test_output_is_never_empty(self):
        for result in (support.load_fixture(), api.NetworkError("x"),
                       RuntimeError("y")):
            text = cli.run(self.cfg, support.NOW,
                           FakeDeps(fetch_result=result).as_deps())
            self.assertTrue(text.strip())



class FetchTtlTest(unittest.TestCase):
    """Rendering runs every 30s; fetching must not. The countdown only needs
    the local clock and the cached reset time."""

    def setUp(self):
        self.addCleanup(support.pin_timezone())
        self.cfg = config.load_config(env={})

    def test_cache_inside_ttl_skips_the_network(self):
        fresh = support.NOW - dt.timedelta(seconds=self.cfg.fetch_ttl - 10)
        fake = FakeDeps(cached=cached_record(fetched_at=fresh))
        cli.run(self.cfg, support.NOW, fake.as_deps())
        self.assertEqual(fake.fetch_calls, 0)

    def test_cache_inside_ttl_is_not_marked_stale(self):
        # Serving a fresh cache is the normal path now, so no hourglass.
        fresh = support.NOW - dt.timedelta(seconds=self.cfg.fetch_ttl - 10)
        fake = FakeDeps(cached=cached_record(fetched_at=fresh))
        text = cli.run(self.cfg, support.NOW, fake.as_deps())
        self.assertEqual(text.splitlines()[0], "◱ 61% · 3h00 · ⚠️")
        self.assertNotIn("⌛", text)

    def test_cache_outside_ttl_does_fetch(self):
        old = support.NOW - dt.timedelta(seconds=self.cfg.fetch_ttl + 10)
        fake = FakeDeps(cached=cached_record(fetched_at=old))
        cli.run(self.cfg, support.NOW, fake.as_deps())
        self.assertEqual(fake.fetch_calls, 1)

    def test_no_cache_always_fetches(self):
        fake = FakeDeps(cached=None)
        cli.run(self.cfg, support.NOW, fake.as_deps())
        self.assertEqual(fake.fetch_calls, 1)

    def test_countdown_advances_across_renders_without_any_fetch(self):
        # The whole point of the decoupling: four 30s renders off one cache.
        fetched = support.NOW
        fake = FakeDeps(cached=cached_record(fetched_at=fetched))
        titles = []
        for offset in (0, 30, 60, 90):
            now = support.NOW + dt.timedelta(seconds=offset)
            text = cli.run(self.cfg, now, fake.as_deps())
            titles.append(text.splitlines()[0])
        self.assertEqual(fake.fetch_calls, 0)
        self.assertIn("3h00", titles[0])
        self.assertIn("2h59", titles[3])

    def test_ttl_does_not_suppress_a_fetch_when_cache_is_unusable(self):
        record = {"version": 1, "fetched_at": support.NOW.isoformat(),
                  "payload": "not-a-dict"}
        fake = FakeDeps(cached=record)
        cli.run(self.cfg, support.NOW, fake.as_deps())
        self.assertEqual(fake.fetch_calls, 1)

    def test_backoff_still_wins_over_a_fresh_cache(self):
        future = support.NOW + dt.timedelta(minutes=5)
        fresh = support.NOW - dt.timedelta(seconds=5)
        fake = FakeDeps(cached=cached_record(fetched_at=fresh,
                                            backoff_until=future))
        text = cli.run(self.cfg, support.NOW, fake.as_deps())
        self.assertEqual(fake.fetch_calls, 0)
        self.assertIn("Rate limited", text)


if __name__ == "__main__":
    unittest.main()
