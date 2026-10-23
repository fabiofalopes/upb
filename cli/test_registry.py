#!/usr/bin/env python3
"""Tests for the upb canonical registry subsystem.

Run: python3 cli/test_registry.py
Requires PyYAML (the same dependency the CLI needs).
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# The CLI is a script, not a package. Load it as a module so the registry
# functions can be tested directly.
import importlib.machinery
import importlib.util

loader = importlib.machinery.SourceFileLoader("upb_cli", str(HERE / "upb"))
spec = importlib.util.spec_from_loader("upb_cli", loader)
upb = importlib.util.module_from_spec(spec)
loader.exec_module(upb)


class TestIdFamily(unittest.TestCase):
    """The family function is what makes rename detection work."""

    def test_version_suffix_stripped(self):
        self.assertEqual(upb._id_family("deepseek-v4-pro:0813"), "deepseek-v4-pro")
        self.assertEqual(upb._id_family("deepseek-v4-pro"), "deepseek-v4-pro")
        self.assertEqual(upb._id_family("gpt-oss:120b"), "gpt-oss")
        self.assertEqual(upb._id_family("nemotron-3-super"), "nemotron-3-super")

    def test_case_insensitive(self):
        self.assertEqual(upb._id_family("GLM-5.2"), upb._id_family("glm-5.2"))

    def test_unrelated_ids_do_not_collide(self):
        self.assertNotEqual(upb._id_family("glm-5.1"), upb._id_family("glm-5.2"))
        self.assertNotEqual(upb._id_family("qwen3-coder-next"),
                            upb._id_family("qwen3-coder"))


class TestRenameDetection(unittest.TestCase):
    """A rename is an id that left while a same-family id arrived."""

    def test_exact_rename(self):
        prev = {"catalogs": {"p": ["deepseek-v4-pro", "glm-5.2"]}}
        cur = {"catalogs": {"p": ["deepseek-v4-pro:0813", "glm-5.2"]}}
        out = upb.detect_renames(prev, cur)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["from"], "deepseek-v4-pro")
        self.assertEqual(out[0]["to"], "deepseek-v4-pro:0813")
        self.assertEqual(out[0]["confidence"], "exact")

    def test_ambiguous_when_many_arrive(self):
        prev = {"catalogs": {"p": ["kimi-k2.6"]}}
        cur = {"catalogs": {"p": ["kimi-k2.6:1", "kimi-k2.6:2"]}}
        out = upb.detect_renames(prev, cur)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["confidence"], "ambiguous")
        self.assertIsNone(out[0]["to"])
        self.assertEqual(len(out[0]["candidates"]), 2)

    def test_no_change_is_no_rename(self):
        prev = {"catalogs": {"p": ["a", "b"]}}
        cur = {"catalogs": {"p": ["a", "b"]}}
        self.assertEqual(upb.detect_renames(prev, cur), [])

    def test_pure_addition_is_not_a_rename(self):
        prev = {"catalogs": {"p": ["a"]}}
        cur = {"catalogs": {"p": ["a", "b"]}}
        self.assertEqual(upb.detect_renames(prev, cur), [])

    def test_provider_added_later_is_skipped(self):
        prev = {"catalogs": {"p": ["a"]}}
        cur = {"catalogs": {"q": ["x"]}}
        self.assertEqual(upb.detect_renames(prev, cur), [])


class TestSlotResolution(unittest.TestCase):
    """The router core: intent slot -> a live, contract-satisfying binding."""

    def _reg(self):
        return {
            "providers": {
                "a": {"enabled": True, "routable": True, "priority": 10},
                "b": {"enabled": True, "routable": True, "priority": 20},
                "c": {"enabled": False, "routable": False, "priority": 5},
            },
            "models": {
                "vendor/cheap": {"capabilities": {"tools": True},
                                 "context_window": 1000},
                "vendor/rich": {"capabilities": {"tools": True, "reasoning": True},
                                "context_window": 200000},
            },
            "bindings": {
                "a/cheap": {"provider": "a", "model_id": "cheap",
                            "canonical": "vendor/cheap", "status": "active",
                            "price": {"input_per_1m": 0.5, "output_per_1m": 1.0}},
                "b/cheap": {"provider": "b", "model_id": "cheap",
                            "canonical": "vendor/cheap", "status": "active",
                            "price": {"input_per_1m": 2.0, "output_per_1m": 5.0}},
                "b/rich": {"provider": "b", "model_id": "rich",
                           "canonical": "vendor/rich", "status": "active",
                           "price": {"input_per_1m": 1.0, "output_per_1m": 2.0}},
                "c/rich": {"provider": "c", "model_id": "rich",
                           "canonical": "vendor/rich", "status": "active",
                           "price": {"input_per_1m": 0.1, "output_per_1m": 0.2}},
            },
            "slots": {
                "primary.coding": {
                    "require": {"capability": "tools"},
                    "cost_ceiling_per_1m": 3.0,
                    "prefer": ["vendor/cheap"],
                    "fallback": ["vendor/rich"],
                }
            },
        }

    def test_prefers_cheapest_under_ceiling(self):
        reg = self._reg()
        bk, info = upb.resolve_slot(reg, {}, "primary.coding")
        self.assertEqual(bk, "a/cheap")
        self.assertEqual(info["tier"], "prefer")

    def test_expensive_binding_falls_back(self):
        reg = self._reg()
        reg["bindings"]["a/cheap"]["price"] = {"input_per_1m": 99.0,
                                               "output_per_1m": 99.0}
        bk, info = upb.resolve_slot(reg, {}, "primary.coding")
        self.assertEqual(bk, "b/cheap")
        self.assertNotEqual(bk, "a/cheap")

    def test_ceiling_applies_to_input_by_default(self):
        """Input price gates by default — that is what coding actually spends."""
        reg = self._reg()
        reg["bindings"]["a/cheap"]["price"] = {"input_per_1m": 0.5,
                                               "output_per_1m": 50.0}
        bk, _ = upb.resolve_slot(reg, {}, "primary.coding")
        self.assertEqual(bk, "a/cheap")

    def test_ceiling_can_apply_to_output(self):
        reg = self._reg()
        reg["slots"]["primary.coding"]["cost_ceiling_applies_to"] = "output"
        # a/cheap blows the output ceiling; b/cheap stays under it
        reg["bindings"]["a/cheap"]["price"] = {"input_per_1m": 0.5,
                                               "output_per_1m": 50.0}
        reg["bindings"]["b/cheap"]["price"] = {"input_per_1m": 2.0,
                                               "output_per_1m": 1.0}
        bk, _ = upb.resolve_slot(reg, {}, "primary.coding")
        self.assertEqual(bk, "b/cheap")

    def test_unpriced_binding_is_routable(self):
        """Unknown price is not evidence of an expensive one."""
        reg = self._reg()
        reg["bindings"]["a/cheap"]["price"] = {}
        bk, _ = upb.resolve_slot(reg, {}, "primary.coding")
        self.assertEqual(bk, "a/cheap")

    def test_unroutable_provider_is_skipped(self):
        reg = self._reg()
        reg["providers"]["a"]["routable"] = False
        bk, _ = upb.resolve_slot(reg, {}, "primary.coding")
        self.assertEqual(bk, "b/cheap")

    def test_provider_that_is_not_the_default_is_still_routable(self):
        """`enabled: false` in routes.yaml means 'not the default route'.

        A metered provider must never be the default, but it is still a valid
        slot target — so it stays routable.
        """
        reg = self._reg()
        reg["providers"]["a"]["enabled"] = False
        bk, _ = upb.resolve_slot(reg, {}, "primary.coding")
        self.assertEqual(bk, "a/cheap")

    def test_deprecated_binding_is_skipped(self):
        reg = self._reg()
        reg["bindings"]["a/cheap"]["status"] = "deprecated"
        bk, _ = upb.resolve_slot(reg, {}, "primary.coding")
        self.assertEqual(bk, "b/cheap")

    def test_capability_contract_is_enforced(self):
        reg = self._reg()
        reg["slots"]["primary.coding"]["require"] = {"capability": "reasoning"}
        bk, info = upb.resolve_slot(reg, {}, "primary.coding")
        self.assertEqual(bk, "b/rich")
        self.assertEqual(info["tier"], "fallback")

    def test_unresolvable_slot_reports_why(self):
        reg = self._reg()
        reg["slots"]["primary.coding"]["require"] = {"capability": "nonexistent"}
        bk, info = upb.resolve_slot(reg, {}, "primary.coding")
        self.assertIsNone(bk)
        self.assertIn("error", info)

    def test_unknown_slot_lists_known_slots(self):
        reg = self._reg()
        bk, info = upb.resolve_slot(reg, {}, "nope")
        self.assertIsNone(bk)
        self.assertIn("primary.coding", info["known"])


class TestValidation(unittest.TestCase):
    """Field rules — the validator is what keeps the registry honest."""

    def _base(self):
        return {
            "providers": {"a": {"enabled": True, "base_url": "https://x/v1",
                                "auth": {"type": "env", "var": "K"}}},
            "models": {"v/m": {"capabilities": {}, "context_window": 100}},
            "bindings": {"a/m": {"provider": "a", "model_id": "m",
                                 "canonical": "v/m", "status": "active",
                                 "status_source": "provider_api",
                                 "status_checked_at": "2026-10-23"}},
            "slots": {},
        }

    def test_clean_registry_has_no_errors(self):
        errs, warns = upb.validate_registry(self._base())
        self.assertEqual(errs, [])

    def test_invalid_status_rejected(self):
        reg = self._base()
        reg["bindings"]["a/m"]["status"] = "banana"
        errs, _ = upb.validate_registry(reg)
        self.assertTrue(any("banana" in e for e in errs))

    def test_unknown_canonical_rejected(self):
        reg = self._base()
        reg["bindings"]["a/m"]["canonical"] = "v/nope"
        errs, _ = upb.validate_registry(reg)
        self.assertTrue(any("not defined" in e for e in errs))

    def test_duplicate_binding_rejected(self):
        reg = self._base()
        reg["bindings"]["a/m2"] = dict(reg["bindings"]["a/m"])
        errs, _ = upb.validate_registry(reg)
        self.assertTrue(any("duplicate" in e for e in errs))

    def test_deprecation_date_requires_source(self):
        reg = self._base()
        reg["bindings"]["a/m"]["deprecation_date"] = "2026-01-01"
        errs, _ = upb.validate_registry(reg)
        self.assertTrue(any("deprecation_source" in e for e in errs))

    def test_secret_material_rejected(self):
        reg = self._base()
        reg["providers"]["a"]["api_key"] = "sk-abcdefghijklmnopqrstuvwxyz012345"
        errs, _ = upb.validate_registry(reg)
        self.assertTrue(any("secret" in e for e in errs))

    def test_slot_preference_must_satisfy_contract(self):
        reg = self._base()
        reg["models"]["v/m"]["capabilities"] = {"tools": False}
        reg["slots"]["s"] = {"require": {"capability": "tools"},
                             "prefer": ["v/m"]}
        errs, warns = upb.validate_registry(reg)
        self.assertTrue(any("does not satisfy" in w for w in warns))

    def test_stale_status_warns(self):
        reg = self._base()
        reg["bindings"]["a/m"]["status_checked_at"] = "2020-01-01"
        errs, warns = upb.validate_registry(reg)
        self.assertTrue(any("stale" in w for w in warns))


class TestRegistryBuild(unittest.TestCase):
    """Build merges routes.yaml + models.dev without losing manual edits."""

    def test_manual_status_survives_rebuild(self):
        cfg = {"providers": {"p": {
            "label": "P", "kind": "upb", "base_url": "https://p/v1",
            "enabled": True, "priority": 10, "key": {"type": "env", "var": "K"},
            "models": {"m1": {"port": 9001}}}}}
        mdev = {"p": {"name": "P", "api": "https://p/v1", "models": {
            "m1": {"id": "m1", "name": "M1", "family": "f", "status": "deprecated",
                   "canonical_model_id": "v/m1", "tool_call": True,
                   "limit": {"context": 1000, "output": 100},
                   "cost": {"input": 1.0, "output": 2.0}}}}}
        # first build: models.dev says deprecated
        reg1 = upb.build_registry(cfg, mdev=mdev, live_catalogs=None)
        self.assertEqual(reg1["bindings"]["p/m1"]["status"], "deprecated")
        self.assertEqual(reg1["bindings"]["p/m1"]["canonical"], "v/m1")
        # mark it by hand as backup, then rebuild
        reg1["bindings"]["p/m1"]["status"] = "backup"
        reg1["bindings"]["p/m1"]["status_source"] = "manual"
        reg1["slots"]["my.slot"] = {"prefer": ["v/m1"]}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "registry.yaml"
            upb.write_registry(reg1, path)
            old = upb.REGISTRY_PATH
            upb.REGISTRY_PATH = path
            try:
                reg2 = upb.build_registry(cfg, mdev=mdev, live_catalogs=None)
            finally:
                upb.REGISTRY_PATH = old
        self.assertEqual(reg2["bindings"]["p/m1"]["status"], "backup")
        self.assertEqual(reg2["bindings"]["p/m1"]["status_source"], "manual")
        self.assertIn("my.slot", reg2["slots"])

    def test_provider_api_outranks_models_dev(self):
        """A provider still serving a model means it is not deprecated."""
        cfg = {"providers": {"p": {
            "label": "P", "kind": "upb", "base_url": "https://p/v1",
            "enabled": True, "key": {"type": "env", "var": "K"},
            "models": {"m1": {}}}}}
        mdev = {"p": {"name": "P", "models": {
            "m1": {"id": "m1", "status": "deprecated",
                   "canonical_model_id": "v/m1"}}}}
        reg = upb.build_registry(cfg, mdev=mdev, live_catalogs={"p": ["m1"]})
        self.assertEqual(reg["bindings"]["p/m1"]["status"], "active")
        self.assertEqual(reg["bindings"]["p/m1"]["status_source"], "provider_api")

    def test_secret_never_lands_in_the_registry(self):
        cfg = {"providers": {"p": {
            "label": "P", "kind": "upb", "base_url": "https://p/v1",
            "enabled": True, "key": {"type": "env", "var": "SECRET_VAR"},
            "models": {"m1": {}}}}}
        reg = upb.build_registry(cfg, mdev={}, live_catalogs=None)
        blob = str(reg)
        self.assertNotIn("SECRET_VAR_VALUE", blob)
        self.assertEqual(reg["providers"]["p"]["auth"]["var"], "SECRET_VAR")


class TestCliSmoke(unittest.TestCase):
    """The commands actually run."""

    def _run(self, *args, **kw):
        env = dict(os.environ)
        env["PYTHONPATH"] = env.get("PYTHONPATH", "")
        return subprocess.run(
            [sys.executable, str(HERE / "upb"), *args],
            capture_output=True, text=True, env=env, **kw)

    def test_snapshot_writes_a_timestamped_file(self):
        """A snapshot is the answer to 'what was I running at time T'."""
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ)
            env.update({"UPB_SNAPSHOTS": str(Path(d) / "snaps"),
                        "UPB_CACHE": str(Path(d) / "cache")})
            r = subprocess.run(
                [sys.executable, str(HERE / "upb"), "snapshot", "--label", "t"],
                capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            files = list((Path(d) / "snaps").glob("*.json"))
            self.assertEqual(len(files), 1)
            snap = json.loads(files[0].read_text())
            for key in ("taken_at", "routes_sha256", "providers", "catalogs", "bindings"):
                self.assertIn(key, snap)
            self.assertEqual(snap["label"], "t")

    def test_snapshot_compares_against_the_previous_one(self):
        """Two snapshots are what a rename shows up in."""
        with tempfile.TemporaryDirectory() as d:
            snaps = Path(d) / "snaps"
            env = dict(os.environ)
            env.update({"UPB_SNAPSHOTS": str(snaps),
                        "UPB_CACHE": str(Path(d) / "cache")})
            for _ in range(2):
                r = subprocess.run(
                    [sys.executable, str(HERE / "upb"), "snapshot"],
                    capture_output=True, text=True, env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len(list(snaps.glob("*.json"))), 2)
            first, second = sorted(snaps.glob("*.json"))
            a = json.loads(first.read_text())
            b = json.loads(second.read_text())
            self.assertNotEqual(a["routes_sha256"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
