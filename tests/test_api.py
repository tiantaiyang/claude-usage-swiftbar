import email.message
import io
import json
import socket
import unittest
import urllib.error

import support
from claude_usage import api, config


def http_error(code, headers=None, body=b""):
    message = email.message.Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError("https://example.invalid", code, "err",
                                  message, io.BytesIO(body))


class Recorder:
    """Stands in for urllib's opener; records the request it was given."""

    def __init__(self, result):
        self.result = result
        self.request = None
        self.timeout = None

    def __call__(self, request, timeout=None):
        self.request = request
        self.timeout = timeout
        if isinstance(self.result, Exception):
            raise self.result
        return io.BytesIO(self.result)


class FetchSuccessTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load_config(env={})
        self.payload = support.load_fixture()
        self.opener = Recorder(json.dumps(self.payload).encode("utf-8"))

    def fetch(self):
        return api.fetch_usage(support.FAKE_TOKEN, self.cfg,
                               opener=self.opener)

    def test_returns_parsed_payload(self):
        self.assertEqual(self.fetch(), self.payload)

    def test_sends_bearer_token_in_authorization_header(self):
        self.fetch()
        self.assertEqual(self.opener.request.get_header("Authorization"),
                         "Bearer " + support.FAKE_TOKEN)

    def test_sends_beta_header(self):
        self.fetch()
        self.assertEqual(self.opener.request.get_header("Anthropic-beta"),
                         self.cfg.beta_header)

    def test_sends_honest_user_agent(self):
        self.fetch()
        agent = self.opener.request.get_header("User-agent")
        self.assertIn("claude-usage-swiftbar", agent)
        self.assertNotIn("claude-cli", agent)

    def test_token_is_never_placed_in_the_url(self):
        self.fetch()
        self.assertNotIn(support.FAKE_TOKEN, self.opener.request.full_url)

    def test_uses_a_get_request(self):
        self.fetch()
        self.assertEqual(self.opener.request.get_method(), "GET")

    def test_applies_configured_timeout(self):
        self.fetch()
        self.assertEqual(self.opener.timeout, self.cfg.timeout)


class FetchFailureTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load_config(env={})

    def fetch(self, result):
        return api.fetch_usage(support.FAKE_TOKEN, self.cfg,
                               opener=Recorder(result))

    def test_401_is_token_rejected(self):
        with self.assertRaises(api.TokenRejected):
            self.fetch(http_error(401))

    def test_403_is_token_rejected(self):
        with self.assertRaises(api.TokenRejected):
            self.fetch(http_error(403))

    def test_429_is_rate_limited_with_retry_after(self):
        with self.assertRaises(api.RateLimited) as caught:
            self.fetch(http_error(429, {"Retry-After": "120"}))
        self.assertEqual(caught.exception.retry_after, 120)

    def test_429_without_retry_after(self):
        with self.assertRaises(api.RateLimited) as caught:
            self.fetch(http_error(429))
        self.assertIsNone(caught.exception.retry_after)

    def test_unparsable_retry_after_is_ignored(self):
        headers = {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
        with self.assertRaises(api.RateLimited) as caught:
            self.fetch(http_error(429, headers))
        self.assertIsNone(caught.exception.retry_after)

    def test_server_error_is_transient(self):
        with self.assertRaises(api.NetworkError):
            self.fetch(http_error(503))

    def test_unexpected_client_error_is_schema_error(self):
        with self.assertRaises(api.UsageApiError):
            self.fetch(http_error(418))

    def test_url_error_is_network_error(self):
        with self.assertRaises(api.NetworkError):
            self.fetch(urllib.error.URLError("no route to host"))

    def test_timeout_is_network_error(self):
        with self.assertRaises(api.NetworkError):
            self.fetch(socket.timeout("timed out"))

    def test_non_json_body_is_schema_error(self):
        with self.assertRaises(api.SchemaError):
            self.fetch(b"<html>maintenance</html>")

    def test_json_that_is_not_an_object_is_schema_error(self):
        with self.assertRaises(api.SchemaError):
            self.fetch(b"[1, 2, 3]")

    def test_all_errors_are_usage_api_errors(self):
        for result in (http_error(401), http_error(429), http_error(503),
                       urllib.error.URLError("x"), b"not json"):
            with self.assertRaises(api.UsageApiError):
                self.fetch(result)

    def test_error_messages_never_leak_the_token(self):
        for result in (http_error(401), http_error(429), http_error(503),
                       urllib.error.URLError("x"), b"not json"):
            try:
                self.fetch(result)
            except api.UsageApiError as error:
                self.assertNotIn(support.FAKE_TOKEN, str(error))
                self.assertNotIn("sk-ant", str(error))


if __name__ == "__main__":
    unittest.main()
