import unittest

import support
from claude_usage import config, keychain


class Runner:
    """Stands in for the subprocess call to /usr/bin/security."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.argv = None

    def __call__(self, argv, timeout=None):
        self.argv = argv
        return self.returncode, self.stdout, self.stderr


class ReadCredentialsTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load_config(env={})

    def read(self, runner):
        return keychain.read_credentials(self.cfg, runner=runner)

    def test_parses_token_and_plan_fields(self):
        creds = self.read(Runner(stdout=support.fake_credentials_json()))
        self.assertEqual(creds.access_token, support.FAKE_TOKEN)
        self.assertEqual(creds.subscription_type, "team")
        self.assertEqual(creds.rate_limit_tier, "default_claude_max_5x")

    def test_queries_the_configured_service_name(self):
        runner = Runner(stdout=support.fake_credentials_json())
        self.read(runner)
        self.assertIn(self.cfg.keychain_service, runner.argv)
        self.assertEqual(runner.argv[0], "/usr/bin/security")

    def test_missing_item_is_not_signed_in(self):
        with self.assertRaises(keychain.NotSignedIn):
            self.read(Runner(returncode=44, stderr="item could not be found"))

    def test_empty_output_is_not_signed_in(self):
        with self.assertRaises(keychain.NotSignedIn):
            self.read(Runner(stdout=""))

    def test_unparsable_output_is_not_signed_in(self):
        with self.assertRaises(keychain.NotSignedIn):
            self.read(Runner(stdout="not json at all"))

    def test_missing_oauth_section_is_not_signed_in(self):
        with self.assertRaises(keychain.NotSignedIn):
            self.read(Runner(stdout='{"mcpOAuth": {}}'))

    def test_blank_token_is_not_signed_in(self):
        with self.assertRaises(keychain.NotSignedIn):
            self.read(Runner(stdout=support.fake_credentials_json(token="")))

    def test_absent_plan_fields_are_none_not_an_error(self):
        stdout = support.fake_credentials_json(subscription=None, tier=None)
        creds = self.read(Runner(stdout=stdout))
        self.assertIsNone(creds.subscription_type)
        self.assertIsNone(creds.rate_limit_tier)
        self.assertEqual(creds.access_token, support.FAKE_TOKEN)


class RedactionTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load_config(env={})
        self.creds = keychain.read_credentials(
            self.cfg, runner=Runner(stdout=support.fake_credentials_json()))

    def test_repr_is_redacted(self):
        self.assertNotIn(support.FAKE_TOKEN, repr(self.creds))
        self.assertNotIn("sk-ant", repr(self.creds))

    def test_str_is_redacted(self):
        self.assertNotIn(support.FAKE_TOKEN, str(self.creds))

    def test_repr_still_identifies_the_object_usefully(self):
        self.assertIn("Credentials", repr(self.creds))
        self.assertIn("team", repr(self.creds))

    def test_formatting_into_a_message_is_redacted(self):
        self.assertNotIn(support.FAKE_TOKEN, "creds={!r}".format(self.creds))

    def test_not_signed_in_message_never_contains_a_token(self):
        try:
            keychain.read_credentials(
                self.cfg,
                runner=Runner(stdout=support.fake_credentials_json(token="")))
        except keychain.NotSignedIn as error:
            self.assertNotIn("sk-ant", str(error))


if __name__ == "__main__":
    unittest.main()
