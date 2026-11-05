#!/usr/bin/env python3
"""Regression tests for the credential-resolution and aux-task bugs.

Both bugs found on 2026-11-05 had the same shape: a tool read a config store,
silently dropped the entry it could not parse, and reported a working system
as broken. Neither was visible in the output — a 401 on a live provider and a
green check on a task that no longer exists both look like ordinary results.

Run:  python3 cli/test_preflight.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import entitlement  # noqa: E402
import preflight  # noqa: E402


class TestCredentialResolution(unittest.TestCase):
    """An env-sourced pool credential must be resolved, not discarded."""

    def _pool(self, tmp, entries):
        # hermes_credentials() reads <home>/.hermes/auth.json, and home is
        # patched to the temp dir — so the file must sit under .hermes/ there.
        (tmp / ".hermes").mkdir(parents=True, exist_ok=True)
        (tmp / ".hermes" / "auth.json").write_text(
            json.dumps({"credential_pool": entries}))
        return tmp

    def test_env_sourced_entry_is_resolved_from_dotenv(self):
        """A pool row with an empty literal key is an env REFERENCE, not a
        placeholder. Dropping it left `commandcode` with only a stale manual
        key, so every probe 401'd on a provider that was answering."""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self._pool(tmp, {
                "commandcode": [
                    {"source": "manual", "priority": 0, "base_url": "https://x/v1",
                     "api_key": "stale-manual-key", "last_status": "exhausted"},
                    {"source": "env:COMMANDCODE_API_KEY", "priority": 1,
                     "base_url": "https://x/v1", "api_key": "",
                     "secret_fingerprint": "sha256:deadbeef"},
                ]})
            with mock.patch.object(entitlement.Path, "home", return_value=tmp), \
                 mock.patch.object(entitlement, "load_env_files",
                                   return_value={"COMMANDCODE_API_KEY": "live-env-key"}):
                creds = entitlement.credentials_for("commandcode")
        self.assertEqual(len(creds), 2,
                         "the env-sourced credential was dropped — this is the bug")
        self.assertEqual(creds[0]["key"], "live-env-key")
        self.assertEqual(creds[0]["source"], "env:COMMANDCODE_API_KEY")

    def test_hard_failed_credential_sinks_below_a_live_one(self):
        """Priority alone is not the runtime's order: a credential the provider
        already rejected must not shadow a working one at a higher priority."""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self._pool(tmp, {
                "commandcode": [
                    {"source": "manual", "priority": 0, "base_url": "https://x/v1",
                     "api_key": "stale", "last_status": "exhausted"},
                    {"source": "env:COMMANDCODE_API_KEY", "priority": 1,
                     "base_url": "https://x/v1", "api_key": "live"},
                ]})
            with mock.patch.object(entitlement.Path, "home", return_value=tmp), \
                 mock.patch.object(entitlement, "load_env_files",
                                   return_value={"COMMANDCODE_API_KEY": "live"}):
                creds = entitlement.credentials_for("commandcode")
        self.assertEqual(creds[0]["key"], "live",
                         "a credential recorded as exhausted was tried first")

    def test_unresolvable_empty_entry_is_still_skipped(self):
        """An empty token that resolves to nothing IS a placeholder, and must
        not shadow a working key. This is the case the old skip was right about."""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self._pool(tmp, {
                "commandcode": [
                    {"source": "env:MISSING_VAR", "priority": 0,
                     "base_url": "https://x/v1", "api_key": ""},
                    {"source": "manual", "priority": 1, "base_url": "https://x/v1",
                     "api_key": "real-key"},
                ]})
            with mock.patch.object(entitlement.Path, "home", return_value=tmp), \
                 mock.patch.object(entitlement, "load_env_files", return_value={}):
                creds = entitlement.credentials_for("commandcode")
        self.assertEqual([c["key"] for c in creds], ["real-key"])


class TestStaleAuxiliaryBlocks(unittest.TestCase):
    """A config block for a task this Hermes no longer runs must be reported,
    not probed. `auxiliary.web_extract` is such a block: probing it produced a
    green check for a task that does not exist."""

    def test_dropped_task_is_reported_as_stale_not_probed(self):
        with mock.patch.object(preflight, "load_cfg", return_value={
                "auxiliary": {
                    "vision": {"provider": "commandcode", "model": "m"},
                    "compression": {"provider": "zai", "model": "m"},
                    "web_extract": {"provider": "commandcode", "model": "m"},
                    "session_search": {"provider": "commandcode", "model": "m"},
                    "not_a_task_at_all": {"provider": "zai", "model": "m"},
                }}):
            known, stale = preflight.known_auxiliary_tasks()
        self.assertIn("web_extract", stale)
        self.assertIn("session_search", stale)
        self.assertIn("not_a_task_at_all", stale)
        self.assertNotIn("vision", stale)
        self.assertNotIn("compression", stale)

    def test_live_tasks_are_not_flagged(self):
        with mock.patch.object(preflight, "load_cfg", return_value={
                "auxiliary": {
                    "vision": {"provider": "commandcode", "model": "m"},
                    "compression": {"provider": "zai", "model": "m"},
                    "mcp": {"provider": "zai", "model": "m"},
                    "approval": {"provider": "zai", "model": "m"},
                    "curator": {"provider": "zai", "model": "m"},
                    "skills_hub": {"provider": "zai", "model": "m"},
                    "title_generation": {"provider": "zai", "model": "m"},
                }}):
            known, stale = preflight.known_auxiliary_tasks()
        self.assertEqual(stale, [])
        self.assertTrue(known)


if __name__ == "__main__":
    unittest.main(verbosity=2)
