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


def cached_record(fetched_at=None, backoff_until=None):
    return {
        "version": 1,
        "fetched_at": (fetched_at or support.NOW).isoformat(),
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
        self.assertEqual(text.splitlines()[0], "◱ 61% · 25% · ⚠️")
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
        self.assertEqual(text.splitlines()[0], "◱ 61% · 25% · ⚠️ ⌛")
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
        self.assertEqual(text.splitlines()[0], "◱ 61% · 25% · ⚠️")

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


if __name__ == "__main__":
    unittest.main()
