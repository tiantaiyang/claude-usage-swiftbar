import json
import os
import pathlib
import stat
import tempfile
import unittest

import support
from claude_usage import cache


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "nested", "snapshot.json")
        self.record = {
            "version": 1,
            "fetched_at": "2026-07-27T03:09:00+00:00",
            "payload": support.load_fixture(),
            "backoff_until": None,
        }

    def test_round_trip(self):
        cache.save(self.path, self.record)
        self.assertEqual(cache.load(self.path), self.record)

    def test_creates_parent_directories(self):
        cache.save(self.path, self.record)
        self.assertTrue(os.path.exists(self.path))

    def test_file_is_owner_only(self):
        cache.save(self.path, self.record)
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode, 0o600)

    def test_missing_file_returns_none(self):
        self.assertIsNone(cache.load(os.path.join(self.tmp.name, "absent.json")))

    def test_corrupt_file_is_treated_as_empty(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertIsNone(cache.load(self.path))

    def test_non_object_file_is_treated_as_empty(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("[1, 2, 3]")
        self.assertIsNone(cache.load(self.path))

    def test_no_temporary_files_left_behind(self):
        cache.save(self.path, self.record)
        siblings = list(pathlib.Path(self.path).parent.iterdir())
        self.assertEqual([p.name for p in siblings], ["snapshot.json"])

    def test_existing_file_survives_a_failed_write(self):
        cache.save(self.path, self.record)
        unserialisable = dict(self.record, payload={"bad": object()})
        with self.assertRaises(Exception):
            cache.save(self.path, unserialisable)
        self.assertEqual(cache.load(self.path), self.record)

    def test_backoff_round_trip(self):
        record = dict(self.record, backoff_until="2026-07-27T03:39:00+00:00")
        cache.save(self.path, record)
        self.assertEqual(cache.load(self.path)["backoff_until"],
                         "2026-07-27T03:39:00+00:00")

    def test_refuses_to_persist_credential_like_keys(self):
        poisoned = dict(self.record,
                        payload={"claudeAiOauth": {"accessToken": support.FAKE_TOKEN}})
        with self.assertRaises(ValueError):
            cache.save(self.path, poisoned)

    def test_nothing_written_when_record_is_rejected(self):
        poisoned = dict(self.record, payload={"refreshToken": "x"})
        with self.assertRaises(ValueError):
            cache.save(self.path, poisoned)
        self.assertFalse(os.path.exists(self.path))

    def test_persisted_bytes_never_contain_a_token(self):
        cache.save(self.path, self.record)
        with open(self.path, encoding="utf-8") as handle:
            written = handle.read()
        self.assertNotIn("sk-ant", written)
        self.assertNotIn(support.FAKE_TOKEN, written)
        # Sanity: the usage numbers really are there.
        self.assertEqual(json.loads(written)["payload"]["five_hour"]["utilization"],
                         61.0)


if __name__ == "__main__":
    unittest.main()
