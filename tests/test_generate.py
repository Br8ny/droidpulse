"""Tests for the pure helpers in scripts/generate.py."""

from __future__ import annotations

import datetime as dt
import unittest

from scripts.generate import categorize, normalize_slug, pulse_score


class GeneratorHelpers(unittest.TestCase):
    def test_normalize_slug(self):
        self.assertEqual(normalize_slug("https://github.com/NewPipe/NewPipe"), "newpipe/newpipe")
        self.assertEqual(normalize_slug("https://github.com/Owner/Repo.git"), "owner/repo")
        self.assertEqual(normalize_slug("git@github.com:Owner/Repo.git"), "owner/repo")
        self.assertEqual(normalize_slug("https://example.com/no"), "")

    def test_categorize(self):
        self.assertEqual(categorize("Puzzle Game"), "Games")
        self.assertEqual(categorize("Password & 2FA"), "Privacy & Security")
        self.assertEqual(categorize("Something Weird"), "Other")
        self.assertEqual(categorize(""), "Other")
        self.assertEqual(categorize("Open Food Network"), "Internet & Network")

    def test_pulse_score(self):
        now = dt.datetime(2026, 1, 1)
        fresh = pulse_score(1000, "2025-12-30T00:00:00Z", "2025-12-28", now)
        stale = pulse_score(1000, "2024-01-01T00:00:00Z", "2024-01-01", now)
        small = pulse_score(10, "2025-12-30T00:00:00Z", "2025-12-28", now)
        self.assertGreater(fresh, stale)
        self.assertGreater(fresh, small)
        self.assertEqual(pulse_score(0, "", "", now), 0.0)


if __name__ == "__main__":
    unittest.main()
