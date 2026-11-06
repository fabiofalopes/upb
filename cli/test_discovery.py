#!/usr/bin/env python3
"""Tests for the health gate's catalogue discovery (§4.1).

The bug this guards against: a provider rotates its catalogue, the declared
list goes dead, and nothing compares the two — so the gate could only grey
models out, never say "the gateway now serves lfm3-1.7b, add it?". A rotation
became an outage instead of a one-line suggestion.

Run:  python3 cli/test_discovery.py
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import health_gate  # noqa: E402


def _surface(models, base="https://gw.example/v1"):
    return {"custom:gw": {"base_url": base, "key": "k", "dialect": "chat",
                          "models": list(models), "ca_cert": None,
                          "verify": True}}


def _probe_ok(base, key, model, dialect, ca_cert=None, verify=True):
    return (True, 200, "usable", "")


def _probe_dead(base, key, model, dialect, ca_cert=None, verify=True):
    return (False, 400, "bad-request", "unsupported model id")


class TestDiscovery(unittest.TestCase):

    def test_rotation_is_proposed_with_the_working_models(self):
        """All declared gone, four new ids serve -> propose exactly those."""
        live = ["lfm2-24b-a2b", "lfm3-1.7b", "stt-large-v3-turbo"]
        with mock.patch.object(health_gate, "fetch_catalogue",
                               return_value=(live, None)), \
             mock.patch.object(health_gate, "probe", _probe_ok), \
             mock.patch.object(health_gate, "_writable_slugs",
                               return_value={"custom:gw"}):
            rows = health_gate.discover(_surface(["amalia-9b", "ornith-9b"]))
        row = rows[0]
        self.assertEqual(row["new"], live)
        self.assertEqual(sorted(row["missing"]), ["amalia-9b", "ornith-9b"])
        self.assertEqual(len(row["proposed"]), 3)
        self.assertTrue(row["writable"])

    def test_unusable_new_models_are_not_proposed(self):
        """Catalogue presence is not entitlement: a new id that 400s is not a
        replacement, and proposing it would repeat the bug in reverse."""
        live = ["a-chat", "stt-only"]
        def probe(base, key, model, dialect, ca_cert=None, verify=True):
            return ((True, 200, "usable", "") if model == "a-chat"
                    else (False, 404, "not-served", "not a chat model"))
        with mock.patch.object(health_gate, "fetch_catalogue",
                               return_value=(live, None)), \
             mock.patch.object(health_gate, "probe", probe), \
             mock.patch.object(health_gate, "_writable_slugs",
                               return_value={"custom:gw"}):
            rows = health_gate.discover(_surface(["dead-1"]))
        self.assertEqual([p["model"] for p in rows[0]["proposed"]], ["a-chat"])
        self.assertEqual([p["model"] for p in rows[0]["not_usable"]], ["stt-only"])

    def test_healthy_declared_list_gets_no_proposal(self):
        """83 undeclared ids on a provider whose declared list is intact is
        noise, not a decision. Only breakage triggers a probe."""
        live = ["declared-a", "declared-b"] + [f"extra-{i}" for i in range(80)]
        probe_mock = mock.Mock(return_value=(True, 200, "usable", ""))
        with mock.patch.object(health_gate, "fetch_catalogue",
                               return_value=(live, None)), \
             mock.patch.object(health_gate, "probe", probe_mock), \
             mock.patch.object(health_gate, "_writable_slugs",
                               return_value={"custom:gw"}):
            rows = health_gate.discover(_surface(["declared-a", "declared-b"]))
        self.assertEqual(rows[0]["missing"], [])
        self.assertEqual(rows[0]["proposed"], [])
        probe_mock.assert_not_called()

    def test_provider_without_a_catalogue_is_reported_not_fatal(self):
        with mock.patch.object(health_gate, "fetch_catalogue",
                               return_value=([], "HTTP 404 on /models")), \
             mock.patch.object(health_gate, "_writable_slugs",
                               return_value={"custom:gw"}):
            rows = health_gate.discover(_surface(["m"]))
        self.assertEqual(rows[0]["catalogue_error"], "HTTP 404 on /models")
        self.assertEqual(rows[0]["proposed"], [])

    def test_pool_provider_is_report_only(self):
        """A pool-served provider's list is not writable from config."""
        live = ["x", "y"]
        with mock.patch.object(health_gate, "fetch_catalogue",
                               return_value=(live, None)), \
             mock.patch.object(health_gate, "probe", _probe_ok), \
             mock.patch.object(health_gate, "_writable_slugs", return_value=set()):
            rows = health_gate.discover(_surface(["gone"]))
        self.assertFalse(rows[0]["writable"])


class TestAdoption(unittest.TestCase):

    def _row(self, live, declared, missing, proposed, not_usable=()):
        return {"provider": "custom:gw", "base_url": "https://gw.example/v1",
                "declared": list(declared), "live": list(live),
                "new": [m for m in live if m not in set(declared)],
                "missing": list(missing), "catalogue_error": None,
                "writable": True,
                "proposed": [{"model": m, "ok": True} for m in proposed],
                "not_usable": [{"model": m} for m in not_usable]}

    def test_appends_and_repoints_a_model_field_outside_the_declared_list(self):
        """The real Lusofona case: `model:` named qwopus3.5-9b-coder, which was
        never in the declared list, so a declared-vs-served diff cannot see it.
        The test is against the live catalogue."""
        cfg = {"custom_providers": [{
            "name": "gw", "base_url": "https://gw.example/v1", "api_key": "k",
            "model": "qwopus3.5-9b-coder",
            "models": {"amalia-9b": {}}}]}
        row = self._row(live=["lfm3-1.7b"], declared=["amalia-9b"],
                        missing=["amalia-9b"], proposed=["lfm3-1.7b"])
        with mock.patch.object(health_gate, "_load_yaml", return_value=cfg), \
             mock.patch.object(health_gate, "save_yaml", return_value=True) as save:
            changes, out = health_gate.adopt_discovery([row])
        entry = out["custom_providers"][0]
        self.assertIn("lfm3-1.7b", entry["models"])
        self.assertEqual(entry["model"], "lfm3-1.7b")
        save.assert_called_once()
        self.assertTrue(any("+1 model" in c for c in changes))
        self.assertTrue(any("not served" in c for c in changes))

    def test_does_not_repoint_when_the_catalogue_could_not_be_read(self):
        """An unread catalogue makes every id look dead. Repointing on that
        would break a healthy provider."""
        cfg = {"custom_providers": [{
            "name": "gw", "base_url": "https://gw.example/v1", "api_key": "k",
            "model": "good-model", "models": {"good-model": {}}}]}
        row = self._row(live=[], declared=["good-model"], missing=[],
                        proposed=[])
        with mock.patch.object(health_gate, "_load_yaml", return_value=cfg), \
             mock.patch.object(health_gate, "save_yaml", return_value=True):
            changes, out = health_gate.adopt_discovery([row])
        self.assertEqual(out["custom_providers"][0]["model"], "good-model")
        self.assertEqual(changes, [])

    def test_healthy_provider_is_untouched(self):
        cfg = {"providers": {"gw": {"api": "https://gw.example/v1",
                                    "model": "a", "models": {"a": {}}}}}
        row = self._row(live=["a"], declared=["a"], missing=[], proposed=[])
        with mock.patch.object(health_gate, "_load_yaml", return_value=cfg), \
             mock.patch.object(health_gate, "save_yaml", return_value=True) as save:
            changes, out = health_gate.adopt_discovery([row])
        self.assertEqual(changes, [])
        save.assert_not_called()

    def test_dry_run_never_writes(self):
        cfg = {"custom_providers": [{
            "name": "gw", "base_url": "https://gw.example/v1", "api_key": "k",
            "models": {"dead": {}}}]}
        row = self._row(live=["new"], declared=["dead"], missing=["dead"],
                        proposed=["new"])
        with mock.patch.object(health_gate, "_load_yaml", return_value=cfg), \
             mock.patch.object(health_gate, "save_yaml", return_value=True) as save:
            changes, _ = health_gate.adopt_discovery([row], dry_run=True)
        save.assert_not_called()
        self.assertTrue(changes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
