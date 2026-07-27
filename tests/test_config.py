import os
import unittest

import support  # noqa: F401  (puts the repo on sys.path)
from claude_usage import config


class DefaultsTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load_config(env={})

    def test_api_url_default(self):
        self.assertEqual(self.cfg.api_url,
                         "https://api.anthropic.com/api/oauth/usage")

    def test_beta_header_default(self):
        self.assertEqual(self.cfg.beta_header, "oauth-2025-04-20")

    def test_keychain_service_default(self):
        self.assertEqual(self.cfg.keychain_service, "Claude Code-credentials")

    def test_threshold_defaults(self):
        self.assertEqual((self.cfg.warn_pct, self.cfg.crit_pct), (80, 95))

    def test_presentation_defaults(self):
        self.assertEqual(self.cfg.bar_width, 10)
        self.assertEqual(self.cfg.glyph, "◱")

    def test_cache_path_is_absolute_and_expanded(self):
        self.assertTrue(os.path.isabs(self.cfg.cache_path))
        self.assertNotIn("~", self.cfg.cache_path)

    def test_config_is_immutable(self):
        with self.assertRaises(AttributeError):
            self.cfg.warn_pct = 1


class OverrideTest(unittest.TestCase):
    def test_every_field_is_env_overridable(self):
        env = {
            "CLAUDE_USAGE_API_URL": "https://example.invalid/usage",
            "CLAUDE_USAGE_BETA_HEADER": "beta-x",
            "CLAUDE_USAGE_TIMEOUT": "3.5",
            "CLAUDE_USAGE_WARN_PCT": "70",
            "CLAUDE_USAGE_CRIT_PCT": "90",
            "CLAUDE_USAGE_BAR_WIDTH": "6",
            "CLAUDE_USAGE_GLYPH": "C",
            "CLAUDE_USAGE_STALE_AFTER": "60",
            "CLAUDE_USAGE_CACHE_PATH": "/tmp/x/snap.json",
            "CLAUDE_USAGE_KEYCHAIN_SERVICE": "Other-credentials",
            "CLAUDE_USAGE_PAGE_URL": "https://example.invalid/settings",
        }
        cfg = config.load_config(env=env)
        self.assertEqual(cfg.api_url, "https://example.invalid/usage")
        self.assertEqual(cfg.beta_header, "beta-x")
        self.assertEqual(cfg.timeout, 3.5)
        self.assertEqual(cfg.warn_pct, 70)
        self.assertEqual(cfg.crit_pct, 90)
        self.assertEqual(cfg.bar_width, 6)
        self.assertEqual(cfg.glyph, "C")
        self.assertEqual(cfg.stale_after, 60)
        self.assertEqual(cfg.cache_path, "/tmp/x/snap.json")
        self.assertEqual(cfg.keychain_service, "Other-credentials")
        self.assertEqual(cfg.usage_page_url,
                         "https://example.invalid/settings")

    def test_invalid_numbers_fall_back_to_defaults(self):
        cfg = config.load_config(env={"CLAUDE_USAGE_WARN_PCT": "abc",
                                      "CLAUDE_USAGE_TIMEOUT": ""})
        self.assertEqual(cfg.warn_pct, 80)
        self.assertEqual(cfg.timeout, 8.0)

    def test_tilde_in_cache_path_is_expanded(self):
        env = {"CLAUDE_USAGE_CACHE_PATH": "~/snap.json"}
        cfg = config.load_config(env=env)
        self.assertTrue(cfg.cache_path.startswith(os.path.expanduser("~")))

    def test_defaults_read_the_process_environment_when_none_given(self):
        self.assertIsInstance(config.load_config().api_url, str)


if __name__ == "__main__":
    unittest.main()
